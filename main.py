import os
import re
import json
import time
import asyncio
import urllib.request
import urllib.parse
from collections import deque
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from google import genai
from google.genai import types
from youtube_transcript_api import YouTubeTranscriptApi

from prompts import (
    PASS1_EXTRACTOR_PROMPT,
    build_user_prompt,
    build_pass2_system_prompt,
)

# ==========================================
# 1. 설정 및 클라이언트 초기화 (Render 환경변수)
# ==========================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPADATA_API_KEY = os.getenv("SUPADATA_API_KEY", "")

# 모델은 Pass별로 따로 지정한다.
# 무료 티어의 호출 한도는 "모델 단위"로 잡히므로, 두 Pass에 다른 모델을 쓰면
# 일일 한도 버킷이 둘로 나뉜다. 동시에 품질이 중요한 Pass 1에만 좋은 모델을 배정할 수 있다.
#
#   GEMINI_MODEL_PASS1 : 자막 → 단별 추출 (누락되면 복구 불가 → 품질 우선)
#   GEMINI_MODEL_PASS2 : 규격화·코수 계산 (오류는 서버 검증기가 잡아냄 → 한도 여유 우선)
#   GEMINI_MODEL       : 위 둘을 지정하지 않았을 때 쓰는 공통 fallback (선택)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
GEMINI_MODEL_PASS1 = os.getenv("GEMINI_MODEL_PASS1") or GEMINI_MODEL or "gemini-3.7-flash"
GEMINI_MODEL_PASS2 = os.getenv("GEMINI_MODEL_PASS2") or GEMINI_MODEL or "gemini-3.1-flash-lite"

ai_client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print(f"🧶 Knotty 기동 — Pass 1: {GEMINI_MODEL_PASS1} / Pass 2: {GEMINI_MODEL_PASS2}")


def _verify_models_on_startup():
    """설정된 모델이 실제로 존재하는지 기동 시 확인한다.

    모델 이름 오타(`gemini-3.1-flash` ↔ `gemini-3.1-flash-lite`)나
    구글이 조용히 은퇴시킨 모델을 **사용자 요청 전에** 로그로 잡아내기 위함이다.
    조회에 실패해도 서비스는 그대로 뜬다.
    """
    try:
        available = {m.name.split("/")[-1] for m in ai_client.models.list()}
    except Exception as e:
        print(f"⚠️ 모델 목록을 조회하지 못해 검증을 건너뜁니다: {str(e)[:120]}")
        return

    for label, name in (("Pass 1", GEMINI_MODEL_PASS1), ("Pass 2", GEMINI_MODEL_PASS2)):
        if name in available:
            print(f"   ✅ {label}: {name}")
        else:
            stem = name.split("-")[0] + "-" + (name.split("-")[1] if "-" in name else "")
            similar = sorted(a for a in available if a.startswith(stem))[:6]
            print(f"   ❌ {label}: '{name}' 은(는) 존재하지 않는 모델입니다."
                  f" 환경변수를 확인하세요. 비슷한 이름: {similar or '(없음)'}")


_verify_models_on_startup()


class QuotaExceededError(Exception):
    """AI 호출 한도 소진. 재시도해도 소용없으므로 사용자에게 그대로 알린다."""
    pass


class ModelOverloadedError(Exception):
    """구글 서버 혼잡(503)이 재시도 후에도 계속됨. 잠시 뒤 다시 하면 대개 풀린다."""
    pass

app = FastAPI(
    title="Knotty API",
    description="유튜브 뜨개질 도안 자동 추출 및 관리 API"
)

# 허용 출처(Origin)는 환경변수로 바꿀 수 있다. 커스텀 도메인을 붙이거나
# 로컬 포트를 바꿀 때 코드를 고치지 않아도 되게 하기 위함이다.
#   ALLOWED_ORIGINS="https://knotty.kr,http://localhost:5500"
_DEFAULT_ORIGINS = [
    "https://hyeom0927.github.io",   # GitHub Pages (운영)
    "http://localhost:5500",         # 로컬 개발 (python -m http.server 5500)
    "http://127.0.0.1:5500",
]
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", ",".join(_DEFAULT_ORIGINS)).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# ------------------------------------------
# 호출량 제한 — Gemini · Supadata 비용 방어
# ------------------------------------------
# `/api/generate`는 한 번 부를 때마다 Gemini 2회 + Supadata 1회가 나간다.
# 주소를 아는 사람이면 누구나 부를 수 있으므로, 방어가 없으면 남의 스크립트가
# 우리 요금을 태울 수 있다. 세 겹으로 막는다.
#
#   ① CORS 허용 출처 — 다른 사이트의 브라우저 코드가 우리 API를 쓰지 못하게 한다.
#   ② IP당 한도    — 한 사람이 연달아 퍼가는 것을 막는다.
#   ③ 전역 일일 한도 — **비용의 상한선.** 무슨 일이 있어도 하루에 이 횟수 이상은
#                      AI를 부르지 않는다. ①②가 모두 뚫려도 손해가 여기서 멈춘다.
#
# 0을 넣으면 그 한도는 꺼진다. 캐시된 도안은 AI를 부르지 않으므로 세지 않는다.
RATE_LIMIT_PER_IP_HOUR  = int(os.getenv("RATE_LIMIT_PER_IP_HOUR", "5"))
RATE_LIMIT_PER_IP_DAY   = int(os.getenv("RATE_LIMIT_PER_IP_DAY", "20"))
RATE_LIMIT_GLOBAL_DAY   = int(os.getenv("RATE_LIMIT_GLOBAL_DAY", "100"))

_HOUR = 3600
_DAY = 86400

# {버킷 이름: 호출 시각 deque}. 프로세스 메모리에만 있으므로 Render가 재시작하면
# 초기화된다. 인스턴스 1대짜리 프로토타입에서는 이 정도로 충분하다.
_rate_events: dict = {}


class RateLimitExceeded(Exception):
    """호출량 한도 초과. 사용자에게 보여줄 문구와 재시도 대기 시간을 함께 담는다."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


def client_ip(request: Request) -> str:
    """호출자의 IP를 찾는다.

    Render는 프록시 뒤에 있어서 request.client.host가 항상 프록시 주소다.
    실제 방문자는 X-Forwarded-For의 **맨 앞** 값이다. (뒤쪽은 중간 프록시들)
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _window_count(bucket: str, window_sec: int, now: float) -> int:
    """버킷에서 창(window) 밖으로 나간 기록을 버리고 남은 개수를 센다."""
    events = _rate_events.get(bucket)
    if events is None:
        events = _rate_events[bucket] = deque()
    while events and now - events[0] > window_sec:
        events.popleft()
    return len(events)


def check_rate_limit(ip: str) -> None:
    """한도를 넘었으면 RateLimitExceeded를 던지고, 통과하면 호출 1건을 기록한다.

    확인과 기록을 한 함수에서 하는 이유는, 실제로 AI를 부르기 직전에 딱 한 번만
    불러야 카운트가 새거나 겹치지 않기 때문이다.
    """
    now = time.time()

    checks = [
        (f"ip:{ip}:hour", RATE_LIMIT_PER_IP_HOUR, _HOUR,
         "잠시만요! 짧은 시간에 너무 많이 만드셨어요. 한 시간쯤 뒤에 다시 시도해 주세요."),
        (f"ip:{ip}:day", RATE_LIMIT_PER_IP_DAY, _DAY,
         "오늘 만들 수 있는 도안 수를 다 쓰셨어요. 내일 다시 시도해 주세요."),
        ("global:day", RATE_LIMIT_GLOBAL_DAY, _DAY,
         "오늘 Knotty 전체의 AI 사용량을 모두 썼어요. 내일 다시 시도해 주세요."),
    ]

    for bucket, limit, window, message in checks:
        if limit <= 0:
            continue
        used = _window_count(bucket, window, now)
        if used >= limit:
            oldest = _rate_events[bucket][0]
            retry_after = max(1, int(window - (now - oldest)))
            print(f"🚦 호출량 제한: {bucket} — {used}/{limit} (재시도까지 {retry_after}초)")
            raise RateLimitExceeded(message, retry_after)

    # 모든 한도를 통과했을 때만 기록한다.
    for bucket, limit, _window, _message in checks:
        if limit > 0:
            _rate_events[bucket].append(now)


print(
    f"🚦 호출량 제한 — IP당 {RATE_LIMIT_PER_IP_HOUR or '무제한'}회/시간, "
    f"{RATE_LIMIT_PER_IP_DAY or '무제한'}회/일 / 전체 {RATE_LIMIT_GLOBAL_DAY or '무제한'}회/일"
)
print(f"🌐 허용 출처 — {', '.join(ALLOWED_ORIGINS) or '(없음)'}")


def refund_rate_limit(ip: str) -> None:
    """AI를 부르지 못하고 끝난 요청의 카운트를 돌려준다.

    한도는 Gemini 비용을 막으려고 두는 것이므로, **AI가 돌지 않았으면 세지 않는다.**
    자막이 없는 영상을 몇 번 시도했다는 이유로 한 시간 잠기는 것은 벌을 잘못 주는 것이다.

    직전에 넣은 기록 하나를 빼는 방식이라, 요청이 겹치면 남의 기록을 뺄 수 있다.
    한도를 조금 느슨하게 만드는 쪽의 오차이고 비용은 전역 상한이 막으므로 감수한다.
    """
    for bucket in (f"ip:{ip}:hour", f"ip:{ip}:day", "global:day"):
        events = _rate_events.get(bucket)
        if events:
            events.pop()


def reject_foreign_origin(request: Request) -> None:
    """다른 사이트에서 온 브라우저 요청을 막는다.

    CORS는 **응답을 읽는 것**만 막을 뿐, 요청 자체는 이미 서버에 도착한다.
    즉 CORS만으로는 AI 호출이 일어나는 것을 막지 못하므로 여기서 한 번 더 본다.

    Origin 헤더가 아예 없는 요청(curl, 서버 간 호출)은 통과시킨다.
    막아도 헤더 한 줄로 우회되는데 로컬 개발과 헬스체크만 불편해지기 때문이다.
    그쪽은 위의 IP·전역 한도가 담당한다.
    """
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        print(f"🚫 허용되지 않은 출처의 호출 차단: {origin}")
        raise HTTPException(status_code=403, detail="허용되지 않은 요청입니다.")


# ==========================================
# 2. Pydantic 요청 스키마 정의
# ==========================================

class PatternRequest(BaseModel):
    youtube_url: str

class PatternUpdateRequest(BaseModel):
    pattern_data: dict

# ==========================================
# 3. 유틸리티, 텍스트 전처리 및 AI 추출 함수
# ==========================================

_VIDEO_ID = r"[0-9A-Za-z_-]{11}"

# 유튜브 주소는 형태가 다양하다. 재생목록·공유 파라미터·shorts·live·모바일·youtu.be 등
# 어떤 형태로 들어와도 같은 영상이면 같은 ID로 수렴해야 캐시가 새지 않는다.
_VIDEO_ID_PATTERNS = [
    re.compile(rf"[?&]v=({_VIDEO_ID})(?![0-9A-Za-z_-])"),            # watch?v= / ?list=…&v=
    re.compile(rf"youtu\.be/({_VIDEO_ID})(?![0-9A-Za-z_-])"),        # 단축 주소
    re.compile(rf"/(?:embed|shorts|live|v)/({_VIDEO_ID})(?![0-9A-Za-z_-])"),
]
_BARE_VIDEO_ID = re.compile(rf"^{_VIDEO_ID}$")


def extract_video_id(url: str) -> str:
    """유튜브 주소(또는 ID)에서 11자리 비디오 ID를 추출한다.

    인식 실패 시 None을 돌려주지 않고 ValueError를 던진다.
    (예전 정규식은 `watch?list=…&v=ID` 형태에서 조용히 None을 반환해
     이후 단계가 잘못된 값으로 진행되었다)
    """
    text = (url or "").strip()
    if not text:
        raise ValueError("유튜브 주소를 입력해 주세요.")

    if _BARE_VIDEO_ID.match(text):
        return text

    # 주소 형태인데 유튜브 도메인이 아니면 거부
    if ("://" in text or "/" in text) and "youtu" not in text.lower():
        raise ValueError("유튜브 영상 주소가 아닙니다.")

    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)

    raise ValueError("유튜브 영상 주소를 인식할 수 없습니다. 영상 링크를 다시 확인해 주세요.")


def canonical_youtube_url(video_id: str) -> str:
    """저장·표시에 쓰는 표준 주소. 재생 위치(t=)나 재생목록 파라미터를 제거한다."""
    return f"https://www.youtube.com/watch?v={video_id}"

# 재시도 대기 시간(초). 503은 구글 쪽 수요 급증이라 몇 초로는 잘 안 풀린다.
# 합계 약 41초까지 기다린다. 자막 분석 자체가 20~60초 걸리므로 체감 차이는 크지 않다.
_RETRY_WAITS = [3, 6, 12, 20]


def call_gemini_with_retry(model_name: str, contents: str, config: types.GenerateContentConfig,
                           max_retries: int = len(_RETRY_WAITS) + 1):
    """503(서버 혼잡) / 429(호출량 초과) 발생 시 지수 대기 후 재시도하는 래퍼

    오류를 네 가지로 나눈다.
      - 404 모델 없음  : 설정 문제. 기다려도 안 되므로 즉시 중단
      - 429 일일 한도  : 기다려도 소용없음 → QuotaExceededError
      - 429 분당 한도  : 잠시 기다리면 풀림 → 재시도
      - 503 서버 혼잡  : 구글 쪽 사정. 가장 길게 기다렸다가 재시도
    """
    for attempt in range(max_retries):
        try:
            return ai_client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
        except Exception as e:
            err_msg = str(e)
            is_overloaded = "503" in err_msg or "UNAVAILABLE" in err_msg or "high demand" in err_msg
            is_rate_limited = "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg
            is_daily_quota = bool(re.search(r"per\s*day|perday|daily", err_msg, re.IGNORECASE))

            # 모델이 없거나 은퇴한 경우 — 재시도해도 소용없고 원인이 분명해야 한다.
            # (구글은 구모델을 조용히 닫으면서 404 NOT_FOUND를 돌려준다)
            if "404" in err_msg or "NOT_FOUND" in err_msg or "no longer available" in err_msg:
                print(f"🚫 [{model_name}] 모델을 사용할 수 없습니다. "
                      f"GEMINI_MODEL_PASS1/PASS2 환경변수를 확인하세요: {err_msg[:200]}")
                raise ValueError(
                    f"'{model_name}' 모델을 사용할 수 없습니다. 서비스 설정의 모델 이름을 확인해 주세요."
                ) from e

            # 어떤 한도에 걸렸는지 원문을 남긴다 (quota 이름이 여기 찍힌다)
            if is_rate_limited:
                print(f"🚫 [{model_name}] 호출량 한도 응답: {err_msg}")

            if is_rate_limited and is_daily_quota:
                raise QuotaExceededError(model_name) from e

            is_last = attempt >= max_retries - 1
            if (is_overloaded or is_rate_limited) and not is_last:
                wait_time = _RETRY_WAITS[min(attempt, len(_RETRY_WAITS) - 1)]
                reason = "429 호출량 초과" if is_rate_limited else "503 서버 혼잡(구글 쪽 수요 급증)"
                print(f"⚠️ [{model_name}] {reason}. {wait_time}초 후 재시도 "
                      f"({attempt + 1}/{max_retries - 1})...")
                time.sleep(wait_time)
                continue

            # 재시도를 다 쓴 경우
            if is_rate_limited:
                raise QuotaExceededError(model_name) from e
            if is_overloaded:
                print(f"🚫 [{model_name}] 서버 혼잡이 계속됩니다 (총 {sum(_RETRY_WAITS)}초 대기 후 포기)")
                raise ModelOverloadedError(model_name) from e
            raise

_PATTERN_KEYS = ("pattern_title", "parts", "pattern_steps", "materials", "total_rows")


def _iter_json_values(text: str) -> list:
    """텍스트에 섞여 있는 최상위 JSON 값들을 순서대로 모두 뽑아낸다.

    `json.loads`는 값 하나만 허용해서, 뒤에 다른 객체나 설명 문장이 붙으면
    'Extra data' 오류를 낸다. raw_decode는 값 하나를 읽고 끝난 위치를 알려주므로
    이어서 다음 값을 찾을 수 있다.
    """
    decoder = json.JSONDecoder()
    found, idx, length = [], 0, len(text)

    while idx < length:
        starts = [p for p in (text.find("{", idx), text.find("[", idx)) if p != -1]
        if not starts:
            break
        start = min(starts)
        try:
            value, end = decoder.raw_decode(text, start)
            found.append(value)
            idx = end
        except json.JSONDecodeError:
            idx = start + 1   # 여는 괄호였지만 JSON이 아니었다면 다음 후보로

    return found


def parse_ai_json(raw_text: str) -> dict:
    """AI 응답에서 도안 JSON을 꺼낸다.

    Gemini는 가끔 이렇게 답한다.
      - ```json 코드펜스로 감쌈
      - JSON 뒤에 설명 문장을 덧붙임
      - 객체를 두 개 이상 연달아 출력함
    어느 경우든 '도안처럼 생긴' 객체를 골라낸다.
    """
    text = (raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE).strip()

    values = _iter_json_values(text)
    if not values:
        preview = text[:300].replace("\n", " ")
        print(f"❌ AI 응답에서 JSON을 찾지 못했습니다 ({len(text)}자): {preview}")
        raise ValueError("AI 응답을 JSON 형태로 파싱할 수 없습니다.")

    if len(values) > 1:
        print(f"⚠️ AI 응답에 JSON 값이 {len(values)}개 있습니다. 도안에 해당하는 것을 고릅니다.")

    # 도안 키를 가장 많이 가진 객체를 고른다
    def score(v):
        return sum(1 for k in _PATTERN_KEYS if isinstance(v, dict) and k in v)

    best = max(values, key=score)
    if score(best) == 0:
        best = values[0]   # 도안처럼 보이는 게 없으면 첫 값

    # 리스트로 답한 경우 딕셔너리로 구조화
    if isinstance(best, list):
        if best and isinstance(best[0], dict) and any(k in best[0] for k in _PATTERN_KEYS):
            best = best[0]
        else:
            best = {"parts": best}

    if not isinstance(best, dict):
        best = {"data": best}

    return best


def clean_pattern_text(text: str) -> str:
    """도안 약어 및 상세 설명에서 불필요한 기둥사슬 부연설명 괄호 문구 제거"""
    if not text:
        return text
    
    patterns = [
        r"\(\s*does\s+not\s+count\s+as\s+(?:a\s+)?st(?:itch)?\s*\)",
        r"\(\s*코로\s*세지\s*않음\s*\)",
        r"\(\s*코수\s*포함\s*X\s*\)",
        r"\(\s*코수에?\s*포함하지?\s*않음\s*\)",
    ]
    
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)
    
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def sanitize_pattern_data(pattern_data: dict) -> dict:
    """DB 저장 직전 pattern_data 전체를 순회하며 formula와 instruction 정제"""
    if not isinstance(pattern_data, dict):
        return pattern_data

    parts = pattern_data.get("parts", [])
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                steps = part.get("steps", [])
                if isinstance(steps, list):
                    for step in steps:
                        if isinstance(step, dict):
                            if "formula" in step and isinstance(step["formula"], str):
                                step["formula"] = clean_pattern_text(step["formula"])
                            if "instruction" in step and isinstance(step["instruction"], str):
                                step["instruction"] = clean_pattern_text(step["instruction"])

    steps = pattern_data.get("pattern_steps", [])
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                if "formula" in step and isinstance(step["formula"], str):
                    step["formula"] = clean_pattern_text(step["formula"])
                if "instruction" in step and isinstance(step["instruction"], str):
                    step["instruction"] = clean_pattern_text(step["instruction"])

    return pattern_data

# ------------------------------------------
# 3-1. 기법 사전(craft_terms) 카탈로그
# ------------------------------------------

_CRAFT_TERMS_CACHE = {"data": None, "ts": 0.0}
_CRAFT_TERMS_TTL = 300  # 초. 기법 사전은 자주 바뀌지 않으므로 5분 캐싱


def get_craft_terms_catalog(force: bool = False) -> list:
    """craft_terms 전체를 조회해 캐싱한다.

    Pass 2 프롬프트 주입 · 사용 기법 매칭 · 코수 검증이 모두 이 카탈로그를 공유한다.
    (요청마다 DB를 3번 때리지 않기 위함)
    """
    now = time.time()
    cached = _CRAFT_TERMS_CACHE["data"]
    if not force and cached is not None and (now - _CRAFT_TERMS_CACHE["ts"]) < _CRAFT_TERMS_TTL:
        return cached

    try:
        res = supabase.table("craft_terms").select("*").execute()
        terms = res.data or []
        _CRAFT_TERMS_CACHE["data"] = terms
        _CRAFT_TERMS_CACHE["ts"] = now
        return terms
    except Exception as e:
        print(f"⚠️ craft_terms 조회 실패: {e}")
        return cached or []


def is_stitch_term(term: dict) -> bool:
    """도안 약어로 쓰이는 기법인지 여부.

    craft_terms에는 약어가 없는 '과정'도 들어간다(배색, 돗바늘 마무리 등).
    이런 항목까지 프롬프트에 주입하면 AI가 formula에 적어 넣어 도안 약어가 오염된다.
    entry_type 컬럼이 없는 경우(구 스키마)는 모두 약어로 간주한다.
    """
    return (term.get("entry_type") or "stitch").strip().lower() != "technique"


def build_terms_catalog_text(catalog: list) -> str:
    """기법 사전을 Pass 2 프롬프트에 넣을 텍스트 목록으로 변환

    용어사전 전용 항목(entry_type='technique')은 제외한다.
    """
    lines = []
    for term in catalog:
        code = (term.get("standard_code") or "").strip()
        if not code or not is_stitch_term(term):
            continue
        kr = (term.get("kr_name") or "").strip()
        # craft_terms.craft_type: crochet / knitting
        craft = (term.get("craft_type") or term.get("needle_type") or "").strip().lower()
        label = {"crochet": "코바늘", "knitting": "대바늘"}.get(craft, craft)
        suffix = f" [{label}]" if label else ""
        lines.append(f"- {code} : {kr}{suffix}")
    return "\n".join(lines)


def get_matching_craft_terms(pattern_data: dict, catalog: list = None) -> list:
    """도안 JSON에 실제로 등장한 기법만 골라 반환"""
    try:
        all_terms = catalog if catalog is not None else get_craft_terms_catalog()
        if not all_terms:
            return []

        full_pattern_str = json.dumps(pattern_data, ensure_ascii=False)

        matched_terms = []
        for term in all_terms:
            code = term.get("standard_code")
            # `sl_st`로 등록된 기법이 도안에 `sl st`로 적혀 있어도 매칭되게 한다
            if code and re.search(_code_to_regex(code), full_pattern_str, re.IGNORECASE):
                matched_terms.append({
                    "standard_code": term.get("standard_code"),
                    "kr_name": term.get("kr_name"),
                    "video_url": term.get("video_url"),
                    "thumbnail_url": term.get("thumbnail_url"),   # 도안 기호 이미지
                    "description": term.get("description")
                })

        return matched_terms
    except Exception as e:
        print(f"⚠️ craft_terms 매칭 실패: {e}")
        return []


def record_unknown_terms(unknown_terms, pattern_id: str = None):
    """기법 사전에 없는 기법을 등록 대기 큐(craft_terms_pending)에 쌓는다.

    같은 표현이 여러 번 등장하면 occurrence_count를 올려, 자주 나오는 것부터
    사전에 등록할 수 있게 한다. 테이블이 없거나 실패해도 도안 생성은 막지 않는다.
    """
    if not unknown_terms or not isinstance(unknown_terms, list):
        return

    for raw in unknown_terms[:20]:  # 폭주 방지
        text = str(raw).strip()
        if not text or len(text) > 100:
            continue
        try:
            existing = supabase.table("craft_terms_pending") \
                .select("id, occurrence_count").eq("raw_text", text).execute()

            if existing.data:
                row = existing.data[0]
                supabase.table("craft_terms_pending").update({
                    "occurrence_count": (row.get("occurrence_count") or 0) + 1
                }).eq("id", row["id"]).execute()
            else:
                supabase.table("craft_terms_pending").insert({
                    "raw_text": text,
                    "occurrence_count": 1,
                    "sample_pattern_id": pattern_id,
                    "status": "pending"
                }).execute()
            print(f"🆕 [미등록 기법] {text}")
        except Exception as e:
            # 테이블 미생성 등 — 매 항목마다 같은 로그를 반복하지 않도록 중단
            print(f"⚠️ craft_terms_pending 기록 실패: {e}")
            return


# ------------------------------------------
# 3-2. 코수 검증
# ------------------------------------------

# 기법 1개가 편물에 남기는 코의 수.
# craft_terms에 stitch_delta 컬럼이 있으면 그 값이 이 기본값을 덮어쓴다.
# 키는 _normalize_code()를 거친 형태(소문자, 언더스코어 → 공백)로 적는다.
# craft_terms.stitch_delta가 있으면 그 값이 이 기본값을 덮어쓴다.
# 여기에도 등록해 두는 이유는 사전 조회가 실패해도 검증이 멈추지 않게 하기 위함이다.
DEFAULT_STITCH_DELTA = {
    # 코바늘 — 기본
    "ch": 1,      # 기둥사슬로 쓰인 경우는 아래에서 0으로 처리
    "sc": 1, "hdc": 1, "dc": 1, "tr": 1, "dtr": 1,
    "sl st": 0, "ss": 0,
    "mr": 0, "mc": 0,
    # 코바늘 — 늘림·줄임
    "inc": 2,     # 한 코에 2번 → 1코 증가
    "dec": 1,     # 2코를 1코로 → 1코 감소
    "sc3tog": 1,
    "sc3inc": 3,    # 한 코에 짧은뜨기 3개
    "hdc2inc": 2,
    "tr3inc": 3,
    "dc2inc": 2,
    "dc4tog": 1,
    "dc2tog": 1, "dc3tog": 1,
    # 코바늘 — 무늬·마무리 (한 코를 먹고 한 코를 남김)
    "puff": 1, "bobble": 1, "popcorn": 1,
    "fpdc": 1, "bpdc": 1, "crab": 1,
    # 코바늘 — 뜨는 위치 지정 (코를 만들지 않음)
    "flo": 0, "blo": 0,
    # 대바늘
    "k": 1, "p": 1,
    "yo": 1,          # 바늘비우기 → 1코 증가
    "k2tog": 1, "ssk": 1, "p2tog": 1,
    "kfb": 2,
    "co": 1,          # 코잡기 N개 → N코
    # bo(코막음)는 일부러 넣지 않는다. 코를 없애는 기법이라 잘못 세면 오탐이 난다 → skipped 처리
}

# 이 기법 1개가 "앞 단에서 써 없애는" 코의 수.
# 생산(stitch_delta)만 보면 약어가 틀렸는지 총 코수가 틀렸는지 구분할 수 없다.
# 소비까지 같이 보면 "앞 단에 없는 코를 떴다"를 잡아내 약어 쪽을 지목할 수 있다.
DEFAULT_STITCH_CONSUME = {
    "ch": 0, "sl st": 0, "ss": 0, "mr": 0, "mc": 0,   # 앞 단 코를 쓰지 않음
    "sc": 1, "hdc": 1, "dc": 1, "tr": 1, "dtr": 1,
    "inc": 1,        # 한 코에 두 번 → 앞 단 1코 사용
    "sc3inc": 1, "hdc2inc": 1, "dc2inc": 1, "tr3inc": 1,
    "dec": 2, "sc3tog": 3, "dc2tog": 2, "dc3tog": 3, "dc4tog": 4,
    "puff": 1, "bobble": 1, "popcorn": 1, "fpdc": 1, "bpdc": 1, "crab": 1,
    "flo": 0, "blo": 0,
    "k": 1, "p": 1, "yo": 0, "k2tog": 2, "ssk": 2, "co": 0,
}

CROCHET_CODES = {"sc", "hdc", "dc", "tr", "dtr", "mr", "sl st", "ch", "inc", "dec"}
KNIT_CODES = {"k", "p", "k2tog", "p2tog", "ssk", "yo", "co", "bo", "kfb"}

# 코수를 바꾸는 기법 (연속성 검사에서 제외 대상)
#
# 기법 목록을 하드코딩하면 사전에 새 기법이 추가될 때마다 여기가 뒤처진다.
# (sc3tog, dc2tog, dc_inc 등이 실제로 누락되어 멀쩡한 단이 경고를 받았다)
# 그래서 뜨개 약어의 작명 관례로 판별한다.
#   ~tog  : 여러 코를 하나로 모으는 줄임  (sc2tog, dc3tog, k2tog …)
#   ~inc  : 늘림                          (inc, dc_inc …)
#   그 외 : dec / ssk / yo / kfb / co / bo
#   `sc 3 in 1 st` 처럼 한 코에 여러 번 뜨는 표기도 코수를 늘린다.
_COUNT_CHANGING = re.compile(
    r"\b\w*tog\b"
    r"|\b\w*inc\b"
    r"|\b(dec|ssk|yo|kfb|co|bo)\b"
    r"|\bin\s+\d+\s*sts?\b",
    re.IGNORECASE
)

# 기법 코드는 숫자·언더스코어를 포함할 수 있다 (k2tog, sl_st).
# 뒤에 공백으로 떨어진 숫자만 개수로 해석한다.
_TOKEN_WITH_COUNT = re.compile(r"^([a-z][a-z0-9_ ]*?)\s+(\d+)$")
# 개수 없이 기법만 적히는 경우(`sl st`, `mr`). 여러 단어로 된 코드도 허용한다.
_TOKEN_ALONE = re.compile(r"^([a-z][a-z0-9_ ]*)$")
# "sc 3 in 1 st" — 한 코에 여러 번 뜨는 표기. 실제 도안에 자주 등장한다.
_TOKEN_IN_ONE = re.compile(r"^([a-z][a-z0-9_ ]*?)\s+(\d+)\s+in\s+\d+\s*sts?$")


def _normalize_code(code: str) -> str:
    """`sl_st` / `sl st` / `SL  ST` 를 같은 코드로 취급한다.

    craft_terms의 standard_code는 `sl_st`인데 도안 표기는 `sl st`라
    정규화하지 않으면 빼뜨기가 들어간 단이 전부 검증에서 빠진다.
    """
    return re.sub(r"[\s_]+", " ", (code or "").strip().lower())


def _code_to_regex(code: str) -> str:
    """`sl_st`와 `sl st`를 모두 잡는 정규식으로 변환"""
    parts = [re.escape(p) for p in re.split(r"[\s_]+", code.strip()) if p]
    return r"\b" + r"[\s_]+".join(parts) + r"\b"


def _split_top_level(text: str) -> list:
    """괄호 안의 쉼표는 무시하고 최상위 쉼표로만 분리"""
    parts, buf, depth = [], "", 0
    for ch in text:
        if ch == "(":
            depth += 1
            buf += ch
        elif ch == ")":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _parse_plain_token(token: str):
    """단일 토큰을 (코드, 개수)로 분해. 해석 불가 시 None"""
    text = token.strip().lower()
    for pattern in (_TOKEN_IN_ONE, _TOKEN_WITH_COUNT):
        match = pattern.match(text)
        if match:
            return _normalize_code(match.group(1)), int(match.group(2))
    match = _TOKEN_ALONE.match(text)
    if match:
        return _normalize_code(match.group(1)), 1
    return None


def _token_code(token: str) -> str:
    parsed = _parse_plain_token(token)
    return parsed[0] if parsed else ""


def _parse_token(token: str, delta_map: dict):
    """단일 토큰 또는 `(...) x N` 그룹의 코수를 계산. 해석 불가 시 None"""
    token = token.strip()

    if token.startswith("("):
        depth, close_idx = 0, -1
        for i, ch in enumerate(token):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
        if close_idx == -1:
            return None

        inner = token[1:close_idx]
        rest = token[close_idx + 1:]
        repeat_match = re.search(r"[x×*]\s*(\d+)", rest, re.IGNORECASE)
        if not repeat_match:
            return None

        inner_total = _parse_sequence(inner, delta_map)
        if inner_total is None:
            return None
        return inner_total * int(repeat_match.group(1))

    parsed = _parse_plain_token(token)
    if not parsed:
        return None

    code, count = parsed
    if code not in delta_map:
        return None
    return delta_map[code] * count


def _parse_sequence(text: str, delta_map: dict, is_row_start: bool = False):
    """도안 약어 한 줄의 최종 코수를 계산. 모르는 기법이 하나라도 있으면 None

    행 맨 앞의 `ch`는 두 가지 의미를 가진다.
      - 기둥사슬  : `ch 1, sc 20` → 코수에 포함하지 않음 (20코)
      - 기초 사슬 : `ch 20`       → 그 자체가 코가 됨 (20코)
    구분 기준은 **뒤에 실제로 뜬 코가 있는지**다. 뒤에 코가 있으면 그 위에 뜬 것이므로
    사슬은 세지 않고, 뒤가 비어 있으면 사슬 자체가 그 단의 결과다.
    (`ch 21, sc 20` 처럼 기초 사슬과 첫 단이 한 줄에 있는 경우도 20코로 올바르게 계산된다)
    """
    tokens = _split_top_level(text)
    if not tokens:
        return None

    values = []
    for token in tokens:
        value = _parse_token(token, delta_map)
        if value is None:
            return None
        values.append([_token_code(token), value])

    # 매직링 등 코를 만들지 않는 선두 토큰은 건너뛴다
    lead = 0
    while lead < len(values) and values[lead][0] in ("mr", "mc"):
        lead += 1

    if is_row_start and lead < len(values) and values[lead][0] == "ch":
        rest = sum(v for _, v in values[lead + 1:])
        if rest > 0:
            values[lead][1] = 0

    return sum(v for _, v in values)


def _count_consumed(text: str, consume_map: dict):
    """이 단이 앞 단에서 써 없애는 코 수. 모르는 기법이 있으면 None"""
    tokens = _split_top_level(text)
    if not tokens:
        return None

    total = 0
    for token in tokens:
        token = token.strip()
        if token.startswith("("):          # (…) x N 반복 그룹
            depth, close = 0, -1
            for i, ch in enumerate(token):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        close = i
                        break
            if close == -1:
                return None
            repeat = re.search(r"[x×*]\s*(\d+)", token[close + 1:], re.IGNORECASE)
            if not repeat:
                return None
            inner = _count_consumed(token[1:close], consume_map)
            if inner is None:
                return None
            total += inner * int(repeat.group(1))
            continue

        parsed = _parse_plain_token(token)
        if not parsed:
            return None
        code, count = parsed
        if code not in consume_map:
            return None
        total += consume_map[code] * count

    return total


def _row_can_change_stitch_count(text: str) -> bool:
    """이 단이 코수를 바꿀 수 있는 요소(늘림·줄임·행 중간 사슬)를 포함하는가"""
    lowered = text.lower()
    if _COUNT_CHANGING.search(lowered):
        return True

    tokens = _split_top_level(lowered)
    lead = 0
    while lead < len(tokens) and _token_code(tokens[lead]) in ("mr", "mc"):
        lead += 1

    # 선두의 기둥사슬 하나만 검사에서 제외한다.
    # (반복 그룹처럼 ch가 행 중간에 있으면 코수를 바꾼다)
    skip_pos = lead if (lead < len(tokens) and _token_code(tokens[lead]) == "ch") else -1

    for pos, token in enumerate(tokens):
        if pos == skip_pos:
            continue
        if re.search(r"\bch\b", token):
            return True
    return False


_GROUPED_ROW = re.compile(r"\d+\s*[~\-–]\s*\d+|반복|repeat", re.IGNORECASE)


def _is_grouped_row(step: dict) -> bool:
    """여러 단을 한 줄로 묶은 스텝인가. (`11~13단`, `메리야스뜨기 반복`)"""
    text = f"{step.get('step_name') or ''} {step.get('row_range') or ''}"
    return bool(_GROUPED_ROW.search(text))


def _validate_steps(steps, delta_map: dict, consume_map: dict = None) -> int:
    """단별 formula를 파싱해 total_stitches와 대조. 불일치 건수 반환

    **경고는 확실할 때만 낸다.** 틀린 경고가 섞이면 맞는 경고까지 무시당하기 때문이다.
    그래서 두 가지는 일부러 검사하지 않는다.

    ① 앞 단의 코를 **적게** 쓰는 단
       많이 쓰는 것은 확실한 오류다 — 앞 단에 없는 코를 뜰 수는 없다.
       그러나 적게 쓰는 것은 정상일 수 있다. 지갑 덮개, 주머니, 트임처럼
       앞 단의 일부에만 뜨는 편물이 실제로 있다. (토마토 지갑 덮개: 앞 단 48코에 sc 20)

    ② 여러 단을 한 줄로 묶었는데 코수가 배수로 나오는 단
       `k 110, p 110` / 총 110코는 겉면·안면 **두 단**을 한 줄로 적은 것이지
       한 단에서 220코를 뜬 것이 아니다. 계산값이 적힌 코수의 정확한 배수라면
       줄 하나에 여러 단이 들어 있다고 보고 검사하지 않는다.
    """
    if not isinstance(steps, list):
        return 0

    consume_map = consume_map or DEFAULT_STITCH_CONSUME
    mismatch_count = 0
    prev_total = None

    for step in steps:
        if not isinstance(step, dict):
            continue

        step.pop("validation", None)

        formula = (step.get("formula") or "").strip()
        expected = step.get("total_stitches")

        # 사용자가 "확인했음"으로 표시한 단은 경고를 다시 띄우지 않는다.
        # 다만 그 이후 약어나 코수가 바뀌면 확인이 무효가 되어야 하므로,
        # 확인 당시의 값을 지문으로 저장해 두고 지금 값과 비교한다.
        ack = step.get("validation_ack")
        if ack and ack != f"{formula}|{expected}":
            step.pop("validation_ack", None)
            ack = None

        # 조립·마무리 단계(코수 0)나 코수 미기재는 검증 대상이 아니다
        if not isinstance(expected, int) or expected <= 0 or not formula:
            continue

        parsed = _parse_sequence(formula.lower(), delta_map, is_row_start=True)
        consumed = _count_consumed(formula.lower(), consume_map)

        if parsed is None:
            # 사전에 없는 기법이 섞인 줄 — 틀린 경고를 내느니 검증하지 않는다
            step["validation"] = {"status": "skipped", "reason": "unknown_term"}
        elif ack:
            # 사람이 이미 확인한 단. 검증은 돌리되 경고로 세지 않는다.
            step["validation"] = {"status": "acknowledged"}
        elif (_is_grouped_row(step) and parsed and expected
              and parsed % expected == 0 and parsed // expected >= 2):
            # ② 한 줄에 여러 단이 들어 있다 — 이 줄만으로는 판단할 수 없다
            step["validation"] = {"status": "skipped", "reason": "grouped_row"}
        elif parsed != expected or (prev_total and consumed is not None
                                    and consumed > prev_total):
            # 생산(남는 코)과 소비(앞 단에서 쓰는 코)를 함께 보면
            # 약어가 틀렸는지 총 코수가 틀렸는지 구분할 수 있다.
            # ① 소비는 **초과일 때만** 오류로 본다 (부분 편물이 정상적으로 존재하므로)
            uses_wrong = (prev_total and consumed is not None
                          and consumed > prev_total)
            if parsed != expected and uses_wrong:
                reason = "formula_stitches"   # 둘 다 어긋남 → 약어에 코가 더/덜 들어감
            elif uses_wrong:
                reason = "formula_uses"       # 남는 코는 맞는데 앞 단보다 많이 씀
            else:
                reason = "total_stitches"     # 약어는 앞 단과 맞는데 총 코수가 다름

            info = {"status": "mismatch", "reason": reason,
                    "expected": expected, "parsed": parsed}
            if uses_wrong:
                info["uses"] = consumed
                info["previous"] = prev_total
            step["validation"] = info
            mismatch_count += 1
        elif (prev_total and prev_total != expected
              and not _row_can_change_stitch_count(formula)
              and not (consumed is not None and consumed < prev_total)):
            # 늘림·줄임이 없는데 앞 단과 코수가 달라진 경우.
            #
            # 단, 앞 단의 코를 다 쓰지 않았다면 코수가 줄어드는 것이 당연하다.
            # (지갑 덮개: 앞 단 48코 중 20코에만 뜨므로 20코가 되는 것이 정상)
            # 이 조건을 빼면 부분 편물이 formula_uses 대신 continuity로 옮겨와
            # 똑같이 틀린 경고를 낸다.
            step["validation"] = {
                "status": "mismatch", "reason": "continuity",
                "expected": expected, "previous": prev_total
            }
            mismatch_count += 1

        # 검증에 걸린 단의 코수는 믿을 수 없으므로 기준선에서 제외한다.
        # (한 단이 틀렸다고 뒤따르는 멀쩡한 단까지 연쇄로 경고되는 것을 막는다)
        # 사람이 확인한 단은 맞다고 판단된 값이므로 기준선으로 그대로 쓴다.
        status = (step.get("validation") or {}).get("status")
        prev_total = expected if status in (None, "acknowledged") else None

    return mismatch_count


def validate_stitch_counts(pattern_data: dict, catalog: list = None) -> dict:
    """도안 전체의 코수를 검증하고 각 step에 validation 정보를 부착한다.

    값을 자동으로 고치지는 않는다. AI가 계산을 두 번 틀릴 여지가 크므로,
    의심스러운 단만 표시해 사용자가 직접 판단하게 하는 것이 목적이다.
    """
    if not isinstance(pattern_data, dict):
        return pattern_data

    delta_map = dict(DEFAULT_STITCH_DELTA)
    for term in (catalog or []):
        code = _normalize_code(term.get("standard_code"))
        delta = term.get("stitch_delta")  # 선택 컬럼
        if code and isinstance(delta, int) and not isinstance(delta, bool):
            delta_map[code] = delta

    mismatch_count = 0
    parts = pattern_data.get("parts")
    if isinstance(parts, list) and parts:
        for part in parts:
            if isinstance(part, dict):
                mismatch_count += _validate_steps(part.get("steps"), delta_map)
    else:
        mismatch_count += _validate_steps(pattern_data.get("pattern_steps"), delta_map)

    pattern_data["validation_summary"] = {"mismatch_count": mismatch_count}
    if mismatch_count:
        print(f"⚠️ 코수 불일치 {mismatch_count}건 감지")

    return pattern_data


def _ts_key(text) -> str:
    """단 이름을 대조용으로 정규화한다. ('11 ~ 13단' → '11~13단')"""
    return re.sub(r"\s+", "", str(text or "")).lower()


def graft_pass1_timestamps(pattern_data: dict, pass1_raw: str) -> dict:
    """Pass 2가 흘린 타임스탬프를 Pass 1 결과에서 되살린다.

    시각의 유일한 출처는 자막이고, 자막을 보는 것은 Pass 1뿐이다.
    Pass 2는 그 값을 옮겨 적기만 하는데, 한도 여유를 위해 더 가벼운 모델을 쓰다 보니
    필드를 통째로 빠뜨리는 일이 있다. 그러면 기능이 **조용히** 죽는다.
    (실제로 이 기능은 그렇게 죽어 있었다 — 저장된 6건 119단 전부 start가 0이었다)

    그래서 Pass 1이 준 값을 서버가 직접 들고 있다가, Pass 2가 비워 놓은 자리에만 채운다.
    Pass 2가 이미 값을 넣었다면 건드리지 않는다.
    """
    if not isinstance(pattern_data, dict):
        return pattern_data

    try:
        pass1 = parse_ai_json(pass1_raw)
    except Exception as e:
        print(f"⏱️ Pass 1 재파싱 실패로 타임스탬프 보충을 건너뜁니다: {e}")
        return pattern_data

    # (파츠명, 단이름) → 초. 파츠명이 달라졌을 때를 대비해 단이름만으로도 찾을 수 있게 둔다.
    by_pair, by_step = {}, {}
    for part in (pass1.get("parts") or []):
        if not isinstance(part, dict):
            continue
        pname = _ts_key(part.get("part_name"))
        for step in (part.get("steps") or []):
            if not isinstance(step, dict):
                continue
            raw = step.get("start_sec")
            if isinstance(raw, str) and raw.strip().isdigit():
                raw = int(raw)
            if not isinstance(raw, (int, float)) or raw <= 0:
                continue
            sname = _ts_key(step.get("step_name") or step.get("row_range"))
            if not sname:
                continue
            by_pair[(pname, sname)] = int(raw)
            # 단 이름이 파츠를 넘어 중복되면(1단이 여러 파츠에 있음) 단독 조회는 포기한다
            by_step[sname] = None if sname in by_step else int(raw)

    if not by_pair:
        print("⏱️ Pass 1이 넘긴 타임스탬프가 없습니다 (자막에 단별 시각이 없는 영상일 수 있음)")
        return pattern_data

    filled = already = 0
    for part in (pattern_data.get("parts") or []):
        if not isinstance(part, dict):
            continue
        pname = _ts_key(part.get("part_name"))
        for step in (part.get("steps") or []):
            if not isinstance(step, dict):
                continue
            ts = step.get("timestamps")
            if not isinstance(ts, dict):
                ts = step["timestamps"] = {"start": 0, "end": 0}

            start = ts.get("start")
            if isinstance(start, (int, float)) and start > 0:
                already += 1
                continue

            sname = _ts_key(step.get("step_name"))
            found = by_pair.get((pname, sname))
            if found is None:
                found = by_step.get(sname)   # 파츠명이 바뀌었을 때의 차선책
            if found:
                ts["start"] = found
                ts.setdefault("end", 0)
                filled += 1

    print(f"⏱️ Pass 1 타임스탬프 {len(by_pair)}개 — Pass 2 전달 {already}개 / 서버 보충 {filled}개")
    return pattern_data


def validate_timestamps(pattern_data: dict, duration_sec: int = 0) -> dict:
    """단별 타임스탬프를 검증한다. 믿을 수 없는 값은 지운다.

    AI는 자막의 시각을 대체로 잘 가져오지만, 뒤로 갈수록 **지어내는 경향**이 있다.
    (실측: 48분 50초 영상인데 마지막 단이 72분 35초를 가리켰다)

    잘못된 시각으로 영상을 열면 엉뚱한 장면이 나와서, 링크가 아예 없는 것보다 나쁘다.
    그래서 의심스러우면 남기지 않고 0으로 지운다.
      - 영상 길이를 넘는 값
      - 앞 단보다 뒤로 가는 값 (뜨개 순서는 되돌아가지 않는다)
    """
    if not isinstance(pattern_data, dict):
        return pattern_data

    parts = pattern_data.get("parts")
    groups = ([p.get("steps") for p in parts if isinstance(p, dict)]
              if isinstance(parts, list) and parts
              else [pattern_data.get("pattern_steps")])

    kept = dropped = 0
    previous = 0

    for steps in groups:
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            ts = step.get("timestamps")
            if not isinstance(ts, dict):
                continue

            start = ts.get("start")
            if not isinstance(start, (int, float)) or start <= 0:
                continue

            start = int(start)
            too_late = duration_sec and start > duration_sec
            goes_back = start < previous

            if too_late or goes_back:
                ts["start"] = 0
                ts["end"] = 0
                dropped += 1
            else:
                previous = start
                kept += 1

    if dropped:
        limit = f"{duration_sec // 60}분 {duration_sec % 60}초" if duration_sec else "알 수 없음"
        print(f"⏱️ 타임스탬프 {kept}개 유지 / {dropped}개 제거 (영상 길이: {limit})")
    elif kept:
        print(f"⏱️ 타임스탬프 {kept}개 모두 유효")

    return pattern_data


def normalize_needle_type(pattern_data: dict) -> dict:
    """materials.needle.type을 '코바늘' 또는 '대바늘'로 정규화"""
    if not isinstance(pattern_data, dict):
        return pattern_data

    materials = pattern_data.get("materials")
    if not isinstance(materials, dict):
        return pattern_data

    needle = materials.get("needle")
    if isinstance(needle, str):
        needle = {"type": needle, "size": needle}
    elif not isinstance(needle, dict):
        return pattern_data

    raw_type = str(needle.get("type") or "")

    if "코바늘" in raw_type or "crochet" in raw_type.lower() or "hook" in raw_type.lower():
        needle["type"] = "코바늘"
    elif "대바늘" in raw_type or "knit" in raw_type.lower():
        needle["type"] = "대바늘"
    else:
        # 표현이 모호하면 도안에 쓰인 약어로 추론한다
        formulas = " ".join(re.findall(r'"formula"\s*:\s*"([^"]*)"',
                                       json.dumps(pattern_data, ensure_ascii=False))).lower()
        crochet_hits = sum(1 for c in CROCHET_CODES if re.search(_code_to_regex(c), formulas))
        knit_hits = sum(1 for c in KNIT_CODES if re.search(_code_to_regex(c), formulas))

        if crochet_hits > knit_hits:
            needle["type"] = "코바늘"
        elif knit_hits > crochet_hits:
            needle["type"] = "대바늘"
        # 추론도 불가능하면 원본 값을 그대로 둔다 (없는 정보를 지어내지 않음)

    materials["needle"] = needle
    return pattern_data

def _fetch_meta_from_page(video_id: str) -> dict:
    """유튜브 워치 페이지를 직접 파싱한다. 가장 정보가 많지만 서버 IP가 차단되면 실패한다."""
    meta = {}
    req = urllib.request.Request(
        f"https://www.youtube.com/watch?v={video_id}",
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9'
        }
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        html = response.read().decode('utf-8', errors='ignore')

    unescape = lambda s: re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)

    desc_match = re.search(r'"shortDescription":"([^"]*)"', html)
    if desc_match:
        meta["description"] = unescape(desc_match.group(1).replace(r'\n', '\n'))
    title_match = re.search(r'"title":"([^"]*)"', html)
    if title_match:
        meta["title"] = unescape(title_match.group(1))
    channel_match = re.search(r'"ownerChannelName":"([^"]*)"', html)
    if channel_match:
        meta["channel_name"] = unescape(channel_match.group(1))
    length_match = re.search(r'"lengthSeconds":"(\d+)"', html)
    if length_match:
        meta["duration_sec"] = int(length_match.group(1))

    # 워치 페이지에는 추천 영상의 channelId도 섞여 있으므로 videoDetails 안의 값만 쓴다
    owner = re.search(r'"videoDetails"\s*:\s*\{.*?"channelId"\s*:\s*"(UC[0-9A-Za-z_-]{22})"', html, re.DOTALL) \
        or re.search(r'"externalChannelId"\s*:\s*"(UC[0-9A-Za-z_-]{22})"', html)
    if owner:
        meta["channel_id"] = owner.group(1)
    handle = re.search(r'"canonicalBaseUrl":"(/@[^"]+)"', html)
    if handle:
        meta["channel_handle"] = handle.group(1).lstrip("/")

    return meta


def _fetch_meta_from_supadata(video_id: str) -> dict:
    """Supadata 영상 메타데이터. 설명란과 channel.id까지 준다 (Render에서도 동작)."""
    key = os.getenv("SUPADATA_API_KEY", "").strip()
    if not key:
        return {}

    req = urllib.request.Request(
        f"https://api.supadata.ai/v1/youtube/video?id={urllib.parse.quote(video_id)}",
        headers={"x-api-key": key}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    channel = data.get("channel") or {}
    meta = {}
    if isinstance(data.get("duration"), (int, float)) and data["duration"] > 0:
        meta["duration_sec"] = int(data["duration"])
    if data.get("title"):
        meta["title"] = data["title"]
    if data.get("description"):
        meta["description"] = data["description"]
    if channel.get("name"):
        meta["channel_name"] = channel["name"]
    if channel.get("id"):
        meta["channel_id"] = channel["id"]
    return meta


def _fetch_meta_from_oembed(video_id: str) -> dict:
    """유튜브 oEmbed. 인증이 필요 없고 차단되지 않는다. 설명란은 주지 않는다."""
    target = urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
    with urllib.request.urlopen(
        f"https://www.youtube.com/oembed?url={target}&format=json", timeout=15
    ) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    meta = {}
    if data.get("title"):
        meta["title"] = data["title"]
    if data.get("author_name"):
        meta["channel_name"] = data["author_name"]
    author_url = data.get("author_url") or ""
    handle = re.search(r"/@([^/?#]+)", author_url)
    if handle:
        meta["channel_handle"] = "@" + handle.group(1)
    return meta


def collect_video_metadata(video_id: str) -> dict:
    """영상 메타데이터를 여러 경로로 모은다.

    Render의 서버 IP는 유튜브에서 차단되어 워치 페이지 파싱이 조용히 실패한다.
    (채널명이 비어 'ownerChannelName' 매치가 안 되고, creators에 "유튜브 채널"이 저장됐다)
    그래서 빈 항목을 다른 경로로 메운다.

      1) 워치 페이지  — 정보가 가장 많음. 차단되면 실패
      2) Supadata     — 설명란 + channel.id 제공. 이미 자막에 쓰고 있는 키
      3) oEmbed       — 인증 불필요·차단 없음. 제목·채널명·핸들만
    """
    meta = {}
    for label, fetch in (("페이지", _fetch_meta_from_page),
                         ("Supadata", _fetch_meta_from_supadata),
                         ("oEmbed", _fetch_meta_from_oembed)):
        # 이미 다 채워졌으면 더 부르지 않는다
        if all(meta.get(k) for k in ("title", "description", "channel_name", "channel_id")):
            break
        try:
            got = fetch(video_id)
        except Exception as e:
            print(f"⚠️ 메타데이터 {label} 실패: {str(e)[:120]}")
            continue
        added = [k for k, v in got.items() if v and not meta.get(k)]
        for k in added:
            meta[k] = got[k]
        if added:
            print(f"📄 메타데이터 {label}에서 보충: {', '.join(added)}")

    missing = [k for k in ("title", "description", "channel_name", "channel_id") if not meta.get(k)]
    if missing:
        print(f"⚠️ 끝내 채우지 못한 메타데이터: {', '.join(missing)}")
    return meta


def get_youtube_data_sync(url: str, video_id: str):
    """영상 메타데이터 + 자막 수집"""
    meta = collect_video_metadata(video_id)

    title         = meta.get("title") or ""
    description   = meta.get("description") or ""
    channel_name  = meta.get("channel_name") or ""
    channel_id    = meta.get("channel_id") or ""
    channel_handle = meta.get("channel_handle") or ""
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    # 채널 주소는 항상 불변 ID로 만든다. 같은 채널이 핸들 주소와 ID 주소로
    # 두 번 저장되는 것을 구조적으로 막기 위함이다.
    channel_url = f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""

    # 2. Supadata API 호출 (Render 유튜브 IP 차단 우회)
    #
    # 실패 원인을 반드시 구분해서 남긴다. 예전에는 어떤 이유로 실패하든 자막이 빈 채로
    # 흘러가서 사용자에게 "이 영상은 자막이 없어요"라고만 알렸는데, 자동 자막이 멀쩡히
    # 있는 영상에서도 같은 말이 나왔다. 다시 시도하면 될 일을 안 된다고 말한 셈이다.
    #   unavailable → 정말 자막이 없음 (다시 해도 소용없음)
    #   outage      → 수집 경로 장애 (잠시 뒤 다시 하면 됨)
    #   quota       → 자막 API 사용량 초과
    #   misconfig   → 키 미설정 (운영자 문제)
    transcript_text = ""
    transcript_error = None
    supadata_key = os.getenv("SUPADATA_API_KEY", "").strip()

    if supadata_key:
        try:
            encoded_url = urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
            sd_url = f"https://api.supadata.ai/v1/youtube/transcript?url={encoded_url}"
            sd_req = urllib.request.Request(
                sd_url,
                headers={"x-api-key": supadata_key}
            )
            with urllib.request.urlopen(sd_req, timeout=60) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                content = data.get("content", [])
                if isinstance(content, list):
                    lines = [f"[{int(item.get('offset', 0)/1000)}s] {item.get('text', '')}" for item in content]
                    transcript_text = "\n".join(lines)
                elif isinstance(content, str):
                    transcript_text = content
            if transcript_text:
                print(f"✅ Supadata 자막 수집 성공! ({len(transcript_text)}자)")
            else:
                # 200인데 내용이 비었다 = 이 영상에 자막 트랙이 없다
                transcript_error = ("unavailable", "Supadata가 빈 자막을 반환")
                print("⚠️ Supadata 응답은 정상이나 자막 내용이 비어 있습니다.")
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode('utf-8', errors='ignore')[:200]
            if e.code == 429:
                transcript_error = ("quota", f"Supadata 429: {err_msg}")
            elif e.code >= 500:
                transcript_error = ("outage", f"Supadata {e.code}: {err_msg}")
            elif e.code in (401, 403):
                transcript_error = ("misconfig", f"Supadata {e.code}: 키 거부됨")
            elif "transcript" in err_msg.lower() or e.code == 404:
                # 자막이 없는 영상이라고 Supadata가 알려준 경우
                transcript_error = ("unavailable", f"Supadata {e.code}: {err_msg}")
            else:
                transcript_error = ("outage", f"Supadata {e.code}: {err_msg}")
            print(f"❌ Supadata HTTP 에러 ({e.code}) → {transcript_error[0]}: {err_msg}")
        except Exception as e:
            # 타임아웃·DNS·연결 끊김 — 전부 일시적 장애로 본다
            transcript_error = ("outage", f"{type(e).__name__}: {str(e)[:150]}")
            print(f"❌ Supadata 호출 예외 → outage: {e}")
    else:
        transcript_error = ("misconfig", "SUPADATA_API_KEY 미설정")
        print("⚠️ SUPADATA_API_KEY 환경변수가 설정되지 않았습니다.")

    # 3. Supadata 미설정/실패 시 Fallback (로컬 전용)
    if not transcript_text:
        try:
            # youtube-transcript-api는 1.x에서 인스턴스 기반 fetch()로 바뀌었다.
            # 정적 get_transcript()만 호출하면 최신 버전에서 AttributeError가 난다.
            try:
                fetched = YouTubeTranscriptApi().fetch(video_id, languages=['ko', 'en'])
                transcript_list = fetched.to_raw_data()
            except AttributeError:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])

            formatted_list = [f"[{int(item['start'])}s] {item['text']}" for item in transcript_list]
            transcript_text = "\n".join(formatted_list)
            print(f"✅ [Fallback] YouTubeTranscriptApi 성공 ({len(transcript_text)}자)")
            transcript_error = None   # 되살아났으니 앞의 실패는 없던 일로 한다
        except Exception as e:
            name = type(e).__name__
            # 라이브러리가 "자막 트랙이 없다"고 명시한 경우만 unavailable로 확정한다.
            # 나머지(IP 차단·네트워크)는 영상 탓이 아니므로 앞선 판정을 유지한다.
            if "NoTranscript" in name or "TranscriptsDisabled" in name:
                transcript_error = ("unavailable", name)
            elif not transcript_error:
                transcript_error = ("outage", f"{name}: {str(e)[:150]}")
            print(f"❌ YouTubeTranscriptApi 실패 → {transcript_error[0]} ({name}): {str(e)[:120]}")

    meta_info = {
        "title": title or "유튜브 뜨개질 영상",
        "description": description,
        "channel_name": channel_name or "유튜브 채널",
        "channel_url": channel_url,
        "channel_id": channel_id,
        "channel_handle": channel_handle,
        "thumbnail_url": thumbnail_url,
        "duration_sec": meta.get("duration_sec") or 0,
        "transcript_error": transcript_error   # (종류, 상세) 또는 None
    }

    return meta_info, transcript_text

def call_gemini_pass1_sync(meta_info: dict, transcript: str) -> str:
    """Pass 1: 잡담 제거 및 단별 핵심 요약 추출"""
    user_data = build_user_prompt(meta_info["title"], meta_info["description"], transcript)
    response = call_gemini_with_retry(
        model_name=GEMINI_MODEL_PASS1,
        contents=user_data,
        config=types.GenerateContentConfig(
            system_instruction=PASS1_EXTRACTOR_PROMPT,
            response_mime_type="application/json"
        )
    )
    return response.text

def call_gemini_pass2_sync(intermediate_json_str: str, meta_info: dict, system_prompt: str = None) -> dict:
    """Pass 2: 도안 규격화 및 최종 정제 (기법 사전을 시스템 프롬프트에 주입)"""
    pass2_input = f"[Pass 1 정제 데이터]\n{intermediate_json_str}\n\n[원본 영상 정보]\n제목: {meta_info['title']}\n설명란: {meta_info['description']}"

    response = call_gemini_with_retry(
        model_name=GEMINI_MODEL_PASS2,
        contents=pass2_input,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt or build_pass2_system_prompt(),
            response_mime_type="application/json"
        )
    )

    final_json = parse_ai_json(response.text)

    final_json["metadata"] = {
        "channel_name": meta_info["channel_name"],
        "channel_url": meta_info["channel_url"],
        "thumbnail_url": meta_info["thumbnail_url"],
        "youtube_url": f"https://www.youtube.com/watch?v={meta_info.get('video_id', '')}"
    }

    return final_json

# ==========================================
# 4. API 엔드포인트
# ==========================================

@app.get("/api/health")
async def health():
    """현재 서버가 어떤 설정으로 떠 있는지 확인한다.

    모델 이름 오타처럼 환경변수가 의심될 때 로그를 못 봐도 바로 알 수 있게 한다.
    비밀값은 노출하지 않고 '설정됨' 여부만 알린다.
    """
    try:
        available = sorted(m.name.split("/")[-1] for m in ai_client.models.list())
    except Exception as e:
        available = None
        list_error = str(e)[:150]
    else:
        list_error = None

    def check(name):
        return {
            "model": name,
            "exists": (name in available) if available is not None else None,
        }

    return {
        "status": "ok",
        "models": {
            "pass1": check(GEMINI_MODEL_PASS1),
            "pass2": check(GEMINI_MODEL_PASS2),
        },
        "env": {
            # 어떤 환경변수가 실제로 들어와 있는지 (값이 아니라 존재 여부만)
            "GEMINI_MODEL": os.getenv("GEMINI_MODEL") or None,
            "GEMINI_MODEL_PASS1": os.getenv("GEMINI_MODEL_PASS1") or None,
            "GEMINI_MODEL_PASS2": os.getenv("GEMINI_MODEL_PASS2") or None,
            "GEMINI_API_KEY": "설정됨" if GEMINI_API_KEY else "없음",
            "SUPABASE_URL": "설정됨" if SUPABASE_URL else "없음",
            "SUPABASE_KEY": "설정됨" if SUPABASE_KEY else "없음",
            "SUPADATA_API_KEY": "설정됨" if SUPADATA_API_KEY else "없음",
        },
        "available_models": available,
        "available_models_error": list_error,
        # 오늘 AI를 몇 번 불렀는지. 한도를 조일지 풀지 판단하는 근거가 된다.
        "rate_limit": {
            "allowed_origins": ALLOWED_ORIGINS,
            "per_ip_hour": RATE_LIMIT_PER_IP_HOUR or "무제한",
            "per_ip_day": RATE_LIMIT_PER_IP_DAY or "무제한",
            "global_day": RATE_LIMIT_GLOBAL_DAY or "무제한",
            "global_used_24h": _window_count("global:day", _DAY, time.time()),
        },
    }


@app.post("/api/generate")
async def generate_pattern(req: PatternRequest, request: Request):
    ip = client_ip(request)
    try:
        reject_foreign_origin(request)
        url = req.youtube_url.strip()

        # 0. 주소 해석 (여기서 걸러야 잘못된 입력이 DB·AI까지 내려가지 않는다)
        try:
            video_id = extract_video_id(url)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))

        canonical_url = canonical_youtube_url(video_id)

        # 1. DB 캐시 확인 — 주소 원문이 아니라 video_id로 조회한다.
        #    `&t=1189s`, `&list=…`, youtu.be 단축 주소가 붙어도 같은 영상이면 캐시가 맞는다.
        existing = supabase.table("patterns").select("*, creators(*)").eq("video_id", video_id).execute()

        # 구버전에 주소 원문으로 저장된 레코드가 있으면 그것도 재사용 (불필요한 AI 호출 방지)
        if not existing.data:
            existing = supabase.table("patterns").select("*, creators(*)").eq("youtube_url", url).execute()

        if existing.data and len(existing.data) > 0:
            cached_record = existing.data[0]
            pattern_data = cached_record["pattern_data"]
            
            craft_terms = get_matching_craft_terms(pattern_data)
            
            print(f"⚡ [Cache Hit] ID: {cached_record['id']}")
            return {
                "status": "success",
                "pattern_id": cached_record["id"],
                "data": pattern_data,
                "craft_terms": craft_terms,
                "creators": cached_record.get("creators"),
                "is_cached": True
            }

        # 여기서부터가 돈이 나가는 구간이다(Supadata 1회 + Gemini 2회).
        # 캐시로 끝나는 요청은 비용이 0이므로 한도에서 빼고, 이 지점에서만 센다.
        # 자막 수집 단계에서 끝나면 Gemini는 돌지 않으므로 아래에서 카운트를 돌려준다.
        check_rate_limit(ip)

        print(f"🔍 [New Request] 분석 시작: {canonical_url}")

        meta_info, transcript = await asyncio.to_thread(get_youtube_data_sync, canonical_url, video_id)
        meta_info["video_id"] = video_id

        # 2. creators 테이블 저장/업데이트 (channel_url 기준 중복 방지)
        creator_id = None
        creator_record = None
        # channel_id를 얻지 못하면 아예 만들지 않는다.
        # 예전에는 핸들 주소로라도 저장했는데, 그 경우 채널명이 기본값("유튜브 채널")로
        # 들어가 쓰레기 행이 쌓였다. 잘못된 채널 정보보다 없는 편이 낫다.
        if meta_info.get("channel_id") and meta_info["channel_url"]:
            base_payload = {
                "channel_name": meta_info["channel_name"] or "미상 채널",
                "channel_url": meta_info["channel_url"]
            }
            full_payload = dict(base_payload)
            if meta_info.get("channel_id"):
                full_payload["channel_id"] = meta_info["channel_id"]
            if meta_info.get("channel_handle"):
                full_payload["channel_handle"] = meta_info["channel_handle"]

            try:
                creator_res = supabase.table("creators").upsert(
                    full_payload, on_conflict="channel_url"
                ).execute()
            except Exception as e:
                # channel_id / channel_handle 컬럼이 아직 없는 스키마에서도 동작하도록
                print(f"⚠️ creators 확장 필드 저장 실패 — 기본 필드로 재시도: {e}")
                creator_res = supabase.table("creators").upsert(
                    base_payload, on_conflict="channel_url"
                ).execute()

            if creator_res.data and len(creator_res.data) > 0:
                creator_record = creator_res.data[0]
                creator_id = creator_record["id"]
                print(f"👤 [Creator] {meta_info['channel_name']} ({meta_info['channel_url']})")
        else:
            print(f"⚠️ 채널 ID를 얻지 못해 creators 저장을 건너뜁니다 "
                  f"(channel_name={meta_info.get('channel_name')!r}). "
                  f"나중에 백필로 채울 수 있습니다.")

        # 💡 자막 수집 실패 — 원인에 따라 다른 안내를 한다.
        #    "다시 하면 되는 일"과 "다시 해도 안 되는 일"을 구분해 주지 않으면
        #    사용자는 멀쩡한 영상을 포기하게 된다.
        if not transcript or not transcript.strip():
            kind, detail = meta_info.get("transcript_error") or ("unavailable", "원인 미상")
            print(f"🚫 자막 수집 실패 [{kind}] {detail}")
            # 여기까지 왔으면 Gemini는 한 번도 부르지 않았다. 한도를 돌려준다.
            refund_rate_limit(ip)

            if kind == "outage":
                raise HTTPException(
                    status_code=503,
                    detail="지금 자막을 가져오는 서버가 불안정해요. 1~2분 뒤에 다시 시도해 주세요."
                )
            if kind == "quota":
                raise HTTPException(
                    status_code=429,
                    detail="오늘 자막 수집 사용량을 모두 썼어요. 내일 다시 시도해 주세요."
                )
            if kind == "misconfig":
                raise HTTPException(
                    status_code=503,
                    detail="자막 수집 설정에 문제가 있어요. 잠시 후 다시 시도해 주세요. (운영자 확인 필요)"
                )
            raise HTTPException(
                status_code=400,
                detail="이 영상은 자막이 없어 정리할 수 없어요. 자막이 있는 영상으로 다시 시도해 주세요."
            )
        
        # 3. AI Pass 1 & Pass 2 실행
        print(f"⏳ Pass 1 실행 중... (모델: {GEMINI_MODEL_PASS1})")
        intermediate_json_str = await asyncio.to_thread(call_gemini_pass1_sync, meta_info, transcript)

        await asyncio.sleep(1.5)

        # 기법 사전을 Pass 2 프롬프트에 주입해, 사전에 있는 약어만 쓰도록 유도한다
        catalog = get_craft_terms_catalog()
        pass2_prompt = build_pass2_system_prompt(build_terms_catalog_text(catalog))

        print(f"⏳ Pass 2 실행 중... (모델: {GEMINI_MODEL_PASS2}, 기법 사전 {len(catalog)}개 주입)")
        pattern_data = await asyncio.to_thread(
            call_gemini_pass2_sync, intermediate_json_str, meta_info, pass2_prompt
        )

        # 사전에 없어 약어로 옮기지 못한 기법은 등록 대기 큐로 보낸다
        unknown_terms = pattern_data.pop("unknown_terms", None)

        pattern_data = sanitize_pattern_data(pattern_data)
        pattern_data = normalize_needle_type(pattern_data)
        # 시각의 출처는 자막뿐이고 자막을 보는 건 Pass 1뿐이다. Pass 2가 흘렸으면 여기서 되살린다.
        pattern_data = graft_pass1_timestamps(pattern_data, intermediate_json_str)
        pattern_data = validate_timestamps(pattern_data, meta_info.get("duration_sec") or 0)
        pattern_data = validate_stitch_counts(pattern_data, catalog)
        db_title = pattern_data.get("pattern_title") or meta_info["title"]

        # 4. patterns 테이블에 저장
        insert_res = supabase.table("patterns").insert({
            "youtube_url": canonical_url,   # 파라미터를 제거한 표준 주소로 저장
            "video_id": video_id,
            "title": db_title,
            "thumbnail_url": meta_info["thumbnail_url"],
            "creator_id": creator_id,
            "pattern_data": pattern_data
        }).execute()

        new_pattern_id = insert_res.data[0]["id"]

        record_unknown_terms(unknown_terms, new_pattern_id)

        craft_terms = get_matching_craft_terms(pattern_data, catalog)

        return {
            "status": "success",
            "pattern_id": new_pattern_id,
            "data": pattern_data,
            "craft_terms": craft_terms,
            "creators": creator_record,
            "is_cached": False
        }

    except HTTPException as he:
        raise he
    except RateLimitExceeded as rle:
        # Retry-After는 초 단위. 브라우저·크롤러가 이 값을 보고 물러난다.
        raise HTTPException(
            status_code=429,
            detail=rle.message,
            headers={"Retry-After": str(rle.retry_after)}
        )
    except QuotaExceededError as qe:
        # AI가 응답을 내주지 못했으므로 사용자의 한도를 깎지 않는다
        refund_rate_limit(ip)
        raise HTTPException(
            status_code=429,
            detail=f"오늘 AI 사용량을 모두 썼어요. 잠시 후 또는 내일 다시 시도해 주세요. (모델: {qe})"
        )
    except ModelOverloadedError as me:
        refund_rate_limit(ip)
        raise HTTPException(
            status_code=503,
            detail="지금 AI 서버가 몰려서 응답하지 못했어요. 1~2분 뒤에 다시 시도해 주세요."
        )
    except ValueError as ve:
        # 모델 이름 오류 등 설정 문제
        raise HTTPException(status_code=500, detail=str(ve))
    except Exception as e:
        print(f"❌ Error in /api/generate: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pattern/{pattern_id}")
async def get_pattern_by_id(pattern_id: str):
    try:
        res = supabase.table("patterns").select("*, creators(*)").eq("id", pattern_id).execute()
        if not res.data or len(res.data) == 0:
            raise HTTPException(status_code=404, detail="해당 도안을 찾을 수 없습니다.")

        record = res.data[0]
        pattern_data = record.get("pattern_data", {})
        record["craft_terms"] = get_matching_craft_terms(pattern_data)

        return {
            "status": "success",
            "data": record
        }
    except HTTPException:
        raise   # 404를 500으로 덮어쓰지 않는다
    except Exception as e:
        print(f"❌ Error in GET /api/pattern: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/pattern/{pattern_id}")
async def update_pattern(pattern_id: str, req: PatternUpdateRequest, request: Request):
    # ⚠️ 아직 인증이 없다. pattern_id만 알면 누구나 덮어쓸 수 있으므로
    #    공개 홍보를 시작하기 전에 편집 토큰이 필요하다. (docs/ROADMAP.md 병행 과제)
    #    지금은 최소한 다른 사이트에서 걸어오는 호출만 막아 둔다.
    reject_foreign_origin(request)
    try:
        sanitized_data = sanitize_pattern_data(req.pattern_data)
        sanitized_data = normalize_needle_type(sanitized_data)
        sanitized_data = validate_timestamps(sanitized_data, 0)
        # 사용자가 코수를 고쳤을 수 있으므로 저장 시점에 다시 검증한다
        sanitized_data = validate_stitch_counts(sanitized_data, get_craft_terms_catalog())

        res = supabase.table("patterns").update({
            "pattern_data": sanitized_data
        }).eq("id", pattern_id).execute()

        if not res.data or len(res.data) == 0:
            raise HTTPException(status_code=404, detail="업데이트할 도안을 찾을 수 없습니다.")

        print(f"📝 [Updated] ID: {pattern_id}")
        return {
            "status": "success",
            "message": "도안이 성공적으로 수정되어 저장되었습니다.",
            "pattern_id": pattern_id,
            "data": sanitized_data
        }
    except HTTPException:
        raise   # 404를 500으로 덮어쓰지 않는다
    except Exception as e:
        print(f"❌ Error in PUT /api/pattern: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
