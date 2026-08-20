import os
import re
import json
import time
import asyncio
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException
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
GEMINI_MODEL_PASS2 = os.getenv("GEMINI_MODEL_PASS2") or GEMINI_MODEL or "gemini-2.5-flash"

ai_client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print(f"🧶 Knotty 기동 — Pass 1: {GEMINI_MODEL_PASS1} / Pass 2: {GEMINI_MODEL_PASS2}")


class QuotaExceededError(Exception):
    """AI 호출 한도 소진. 재시도해도 소용없으므로 사용자에게 그대로 알린다."""
    pass

app = FastAPI(
    title="Knotty API",
    description="유튜브 뜨개질 도안 자동 추출 및 관리 API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

def extract_video_id(url: str) -> str:
    """유튜브 URL에서 11자리 비디오 ID 추출"""
    regex = r"(?:v=|\/([0-9A-Za-z_-]{11}).*|list=|\/embed\/|\/v\/|https:\/\/youtu\.be\/)([^#\&\?]*)"
    match = re.search(regex, url)
    if match:
        return match.group(2) if len(match.group(2)) == 11 else match.group(1)
    raise ValueError("올바른 유튜브 URL 형식이 아닙니다.")

def call_gemini_with_retry(model_name: str, contents: str, config: types.GenerateContentConfig, max_retries: int = 3):
    """503(서버 혼잡) / 429(호출량 초과) 발생 시 지수 대기 후 재시도하는 래퍼

    429는 두 종류를 구분한다.
      - 분당 한도(RPM/TPM) 초과 : 잠시 기다리면 풀리므로 재시도
      - 일일 한도 초과          : 기다려도 소용없으므로 즉시 QuotaExceededError
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

            # 어떤 한도에 걸렸는지 원문을 남긴다 (quota 이름이 여기 찍힌다)
            if is_rate_limited:
                print(f"🚫 [{model_name}] 호출량 한도 응답: {err_msg}")

            if is_rate_limited and (is_daily_quota or attempt == max_retries - 1):
                raise QuotaExceededError(model_name) from e

            if (is_overloaded or is_rate_limited) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2
                reason = "429 호출량 초과" if is_rate_limited else "503 서버 혼잡"
                print(f"⚠️ [{model_name}] {reason}. {wait_time}초 후 재시도 ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise

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


def build_terms_catalog_text(catalog: list) -> str:
    """기법 사전을 Pass 2 프롬프트에 넣을 텍스트 목록으로 변환"""
    lines = []
    for term in catalog:
        code = (term.get("standard_code") or "").strip()
        if not code:
            continue
        kr = (term.get("kr_formal") or "").strip()
        needle = (term.get("needle_type") or "").strip()  # 선택 컬럼
        suffix = f" [{needle}]" if needle else ""
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
            if code and re.search(rf"\b{re.escape(code)}\b", full_pattern_str, re.IGNORECASE):
                matched_terms.append({
                    "standard_code": term.get("standard_code"),
                    "kr_formal": term.get("kr_formal"),
                    "video_url": term.get("video_url")
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
DEFAULT_STITCH_DELTA = {
    "ch": 1,      # 기둥사슬로 쓰인 경우는 아래에서 0으로 처리
    "sc": 1, "hdc": 1, "dc": 1, "tr": 1, "dtr": 1,
    "inc": 2,     # 한 코에 2번 → 1코 증가
    "dec": 1,     # 2코를 1코로 → 1코 감소
    "sl st": 0, "ss": 0,
    "mr": 0, "mc": 0,
}

CROCHET_CODES = {"sc", "hdc", "dc", "tr", "dtr", "mr", "sl st", "ch"}
KNIT_CODES = {"k", "p", "k2tog", "p2tog", "ssk", "yo", "co", "bo", "kfb"}

_TOKEN_RE = re.compile(r"^([a-z][a-z ]*?)\s*(\d+)?$")


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


def _token_code(token: str) -> str:
    match = _TOKEN_RE.match(token.strip().lower())
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1).strip())


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

    match = _TOKEN_RE.match(token.lower())
    if not match:
        return None

    code = re.sub(r"\s+", " ", match.group(1).strip())
    count = int(match.group(2)) if match.group(2) else 1
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


def _row_can_change_stitch_count(text: str) -> bool:
    """이 단이 코수를 바꿀 수 있는 요소(늘림·줄임·행 중간 사슬)를 포함하는가"""
    lowered = text.lower()
    if re.search(r"\b(inc|dec)\b", lowered):
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


def _validate_steps(steps, delta_map: dict) -> int:
    """단별 formula를 파싱해 total_stitches와 대조. 불일치 건수 반환"""
    if not isinstance(steps, list):
        return 0

    mismatch_count = 0
    prev_total = None

    for step in steps:
        if not isinstance(step, dict):
            continue

        step.pop("validation", None)

        formula = (step.get("formula") or "").strip()
        expected = step.get("total_stitches")

        # 조립·마무리 단계(코수 0)나 코수 미기재는 검증 대상이 아니다
        if not isinstance(expected, int) or expected <= 0 or not formula:
            continue

        parsed = _parse_sequence(formula.lower(), delta_map, is_row_start=True)

        if parsed is None:
            # 사전에 없는 기법이 섞인 줄 — 틀린 경고를 내느니 검증하지 않는다
            step["validation"] = {"status": "skipped", "reason": "unknown_term"}
        elif parsed != expected:
            step["validation"] = {
                "status": "mismatch", "reason": "formula",
                "expected": expected, "parsed": parsed
            }
            mismatch_count += 1
        elif (prev_total and prev_total != expected
              and not _row_can_change_stitch_count(formula)):
            # 늘림·줄임이 없는데 앞 단과 코수가 달라진 경우
            step["validation"] = {
                "status": "mismatch", "reason": "continuity",
                "expected": expected, "previous": prev_total
            }
            mismatch_count += 1

        # 검증에 걸린 단의 코수는 믿을 수 없으므로 기준선에서 제외한다.
        # (한 단이 틀렸다고 뒤따르는 멀쩡한 단까지 연쇄로 경고되는 것을 막는다)
        prev_total = expected if step.get("validation") is None else None

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
        code = (term.get("standard_code") or "").strip().lower()
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
        crochet_hits = sum(1 for c in CROCHET_CODES if re.search(rf"\b{re.escape(c)}\b", formulas))
        knit_hits = sum(1 for c in KNIT_CODES if re.search(rf"\b{re.escape(c)}\b", formulas))

        if crochet_hits > knit_hits:
            needle["type"] = "코바늘"
        elif knit_hits > crochet_hits:
            needle["type"] = "대바늘"
        # 추론도 불가능하면 원본 값을 그대로 둔다 (없는 정보를 지어내지 않음)

    materials["needle"] = needle
    return pattern_data

def get_youtube_data_sync(url: str, video_id: str):
    """유튜브 메타데이터 수집 및 Supadata API 기반 자막 수집"""
    title, description, channel_name, channel_url = "", "", "", ""
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    # 1. 페이지 직접 파싱을 통한 메타데이터 추출
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'ko-KR,ko;q=0.9'
            }
        )
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8', errors='ignore')
            desc_match = re.search(r'"shortDescription":"([^"]*)"', html)
            if desc_match:
                raw_desc = desc_match.group(1).replace(r'\n', '\n')
                description = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), raw_desc)
            title_match = re.search(r'"title":"([^"]*)"', html)
            if title_match:
                raw_title = title_match.group(1)
                title = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), raw_title)
            channel_match = re.search(r'"ownerChannelName":"([^"]*)"', html)
            if channel_match:
                channel_name = channel_match.group(1)

            # 채널 URL 추출 — creators 테이블의 중복 방지 키(UNIQUE)로 사용됨.
            # 핸들(@name)은 변경될 수 있으므로 불변인 channelId를 우선한다.
            channel_id_match = re.search(r'"channelId":"(UC[0-9A-Za-z_-]{22})"', html)
            if channel_id_match:
                channel_url = f"https://www.youtube.com/channel/{channel_id_match.group(1)}"
            else:
                handle_match = re.search(r'"canonicalBaseUrl":"(/@[^"]+)"', html)
                if handle_match:
                    channel_url = f"https://www.youtube.com{handle_match.group(1)}"
    except Exception as e:
        print(f"⚠️ 페이지 파싱 경고: {e}")

    # 2. Supadata API 호출 (Render 유튜브 IP 차단 우회)
    transcript_text = ""
    supadata_key = os.getenv("SUPADATA_API_KEY", "").strip()

    if supadata_key:
        try:
            encoded_url = urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
            sd_url = f"https://api.supadata.ai/v1/youtube/transcript?url={encoded_url}"
            sd_req = urllib.request.Request(
                sd_url, 
                headers={"x-api-key": supadata_key}
            )
            with urllib.request.urlopen(sd_req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                content = data.get("content", [])
                if isinstance(content, list):
                    lines = [f"[{int(item.get('offset', 0)/1000)}s] {item.get('text', '')}" for item in content]
                    transcript_text = "\n".join(lines)
                elif isinstance(content, str):
                    transcript_text = content
                print(f"✅ Supadata 자막 수집 성공! ({len(transcript_text)}자)")
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode('utf-8', errors='ignore')
            print(f"❌ Supadata HTTP 에러 ({e.code}): {err_msg}")
        except Exception as e:
            print(f"❌ Supadata 호출 예외: {e}")
    else:
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
        except Exception as e:
            print(f"❌ YouTubeTranscriptApi 실패 (Render IP 차단 또는 자막 없음): {e}")

    meta_info = {
        "title": title or "유튜브 뜨개질 영상",
        "description": description,
        "channel_name": channel_name or "유튜브 채널",
        "channel_url": channel_url,
        "thumbnail_url": thumbnail_url
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

    raw_final_text = response.text.strip()
    raw_final_text = re.sub(r"^```(?:json)?\s*", "", raw_final_text, flags=re.MULTILINE)
    raw_final_text = re.sub(r"```\s*$", "", raw_final_text, flags=re.MULTILINE).strip()

    try:
        final_json = json.loads(raw_final_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_final_text, re.DOTALL)
        if match:
            final_json = json.loads(match.group(0))
        else:
            raise ValueError("AI 응답을 JSON 형태로 파싱할 수 없습니다.")

    # 💡 [방어 코드] Gemini가 리스트([]) 형태로 반환했을 경우 딕셔너리로 구조화
    if isinstance(final_json, list):
        if len(final_json) > 0 and isinstance(final_json[0], dict) and ("parts" in final_json[0] or "pattern_steps" in final_json[0] or "pattern_title" in final_json[0]):
            final_json = final_json[0]
        else:
            final_json = {"parts": final_json}

    if not isinstance(final_json, dict):
        final_json = {"data": final_json}

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

@app.post("/api/generate")
async def generate_pattern(req: PatternRequest):
    try:
        url = req.youtube_url.strip()
        
        # 1. DB 캐시 확인
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

        print(f"🔍 [New Request] 분석 시작: {url}")
        video_id = extract_video_id(url)
        
        meta_info, transcript = await asyncio.to_thread(get_youtube_data_sync, url, video_id)
        meta_info["video_id"] = video_id

        # 2. creators 테이블 저장/업데이트 (channel_url 기준 중복 방지)
        creator_id = None
        creator_record = None
        if meta_info["channel_url"]:
            creator_res = supabase.table("creators").upsert(
                {
                    "channel_name": meta_info["channel_name"] or "미상 채널",
                    "channel_url": meta_info["channel_url"]
                },
                on_conflict="channel_url"
            ).execute()

            if creator_res.data and len(creator_res.data) > 0:
                creator_record = creator_res.data[0]
                creator_id = creator_record["id"]
                print(f"👤 [Creator] {meta_info['channel_name']} ({meta_info['channel_url']})")
        else:
            print("⚠️ channel_url 파싱 실패 — creators 저장을 건너뜁니다.")

        # 💡 자막 수집 실패 시 예외 처리
        if not transcript or not transcript.strip():
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
        pattern_data = validate_stitch_counts(pattern_data, catalog)
        db_title = pattern_data.get("pattern_title") or meta_info["title"]

        # 4. patterns 테이블에 저장
        insert_res = supabase.table("patterns").insert({
            "youtube_url": url,
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
    except QuotaExceededError as qe:
        raise HTTPException(
            status_code=429,
            detail=f"오늘 AI 사용량을 모두 썼어요. 잠시 후 또는 내일 다시 시도해 주세요. (모델: {qe})"
        )
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
    except Exception as e:
        print(f"❌ Error in GET /api/pattern: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/pattern/{pattern_id}")
async def update_pattern(pattern_id: str, req: PatternUpdateRequest):
    try:
        sanitized_data = sanitize_pattern_data(req.pattern_data)
        sanitized_data = normalize_needle_type(sanitized_data)
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
    except Exception as e:
        print(f"❌ Error in PUT /api/pattern: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
