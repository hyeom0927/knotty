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

from prompts import PASS1_EXTRACTOR_PROMPT, PASS2_REFINER_PROMPT, build_user_prompt

# ==========================================
# 1. 설정 및 클라이언트 초기화 (Render 환경변수)
# ==========================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPADATA_API_KEY = os.getenv("SUPADATA_API_KEY", "")

ai_client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
    """503/429 서버 혼잡 에러 발생 시 자동으로 지수 대기 후 재시도하는 래퍼 함수"""
    for attempt in range(max_retries):
        try:
            return ai_client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
        except Exception as e:
            err_msg = str(e)
            if ("503" in err_msg or "UNAVAILABLE" in err_msg or "high demand" in err_msg) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2
                print(f"⚠️ Google API 503 서버 혼잡 발생. {wait_time}초 후 자동 재시도합니다 ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise e

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
    for part in parts:
        for step in part.get("steps", []):
            if "formula" in step and step["formula"]:
                step["formula"] = clean_pattern_text(step["formula"])
            if "instruction" in step and step["instruction"]:
                step["instruction"] = clean_pattern_text(step["instruction"])

    steps = pattern_data.get("pattern_steps", [])
    for step in steps:
        if "formula" in step and step["formula"]:
            step["formula"] = clean_pattern_text(step["formula"])
        if "instruction" in step and step["instruction"]:
            step["instruction"] = clean_pattern_text(step["instruction"])

    return pattern_data

def get_matching_craft_terms(pattern_data: dict) -> list:
    """도안 JSON 데이터를 분석하여 craft_terms DB와 매칭된 기법 목록 반환"""
    try:
        terms_res = supabase.table("craft_terms").select("standard_code, kr_formal, video_url").execute()
        all_terms = terms_res.data or []

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
        print(f"⚠️ craft_terms DB 연동 실패: {e}")
        return []

def get_youtube_data_sync(url: str, video_id: str):
    """유튜브 메타데이터 수집 및 Supadata API 기반 자막 수집 (Fallback: YouTubeTranscriptApi)"""
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
    except Exception as e:
        print(f"⚠️ 페이지 파싱 경고: {e}")

    # 2. Supadata API 우선 호출 (Render 유튜브 IP 차단 100% 회피)
    transcript_text = ""
    supadata_key = os.getenv("SUPADATA_API_KEY")

    if supadata_key:
        try:
            sd_url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&lang=ko"
            sd_req = urllib.request.Request(
                sd_url, 
                headers={"x-api-key": supadata_key}
            )
            with urllib.request.urlopen(sd_req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                content = data.get("content", [])
                lines = [f"[{int(item['offset']/1000)}s] {item['text']}" for item in content]
                transcript_text = "\n".join(lines)
                print(f"✅ Supadata 자막 수집 성공! ({len(lines)}개 문장)")
        except Exception as e:
            print(f"⚠️ Supadata 자막 수집 실패: {e}")

    # 3. Supadata Key 미설정 또는 실패 시 로컬 개발환경용 Fallback
    if not transcript_text:
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
            formatted_list = [f"[{int(item['start'])}s] {item['text']}" for item in transcript_list]
            transcript_text = "\n".join(formatted_list)
            print(f"✅ [Fallback] YouTubeTranscriptApi 자막 수집 성공! ({len(formatted_list)}개 문장)")
        except Exception as e:
            print(f"❌ YouTubeTranscriptApi 수집 실패 (Render IP 차단): {e}")

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
        model_name='gemini-2.5-flash',
        contents=user_data,
        config=types.GenerateContentConfig(
            system_instruction=PASS1_EXTRACTOR_PROMPT,
            response_mime_type="application/json"
        )
    )
    return response.text

def call_gemini_pass2_sync(intermediate_json_str: str, meta_info: dict) -> dict:
    """Pass 2: 도안 규격화 및 최종 정제"""
    pass2_input = f"[Pass 1 정제 데이터]\n{intermediate_json_str}\n\n[원본 영상 정보]\n제목: {meta_info['title']}\n설명란: {meta_info['description']}"
    
    response = call_gemini_with_retry(
        model_name='gemini-2.5-flash',
        contents=pass2_input,
        config=types.GenerateContentConfig(
            system_instruction=PASS2_REFINER_PROMPT,
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

        # 2. creators 테이블 저장/업데이트
        creator_id = None
        if meta_info["channel_url"]:
            creator_res = supabase.table("creators").upsert(
                {
                    "channel_name": meta_info["channel_name"] or "미상 채널",
                    "channel_url": meta_info["channel_url"]
                },
                on_conflict="channel_url"
            ).execute()
            
            if creator_res.data and len(creator_res.data) > 0:
                creator_id = creator_res.data[0]["id"]

        # 💡 자막 수집 실패 시 부실 요약본 생성을 방지하기 위한 예외 처리
        if not transcript or not transcript.strip():
            raise HTTPException(
                status_code=400, 
                detail="유튜브 자막 수집에 실패했습니다. Render 대시보드의 SUPADATA_API_KEY 설정 및 자막 제공 여부를 확인해주세요."
            )
        
        # 3. AI Pass 1 & Pass 2 실행
        print("⏳ Pass 1 실행 중...")
        intermediate_json_str = await asyncio.to_thread(call_gemini_pass1_sync, meta_info, transcript)

        await asyncio.sleep(1.5)

        print("⏳ Pass 2 실행 중...")
        pattern_data = await asyncio.to_thread(call_gemini_pass2_sync, intermediate_json_str, meta_info)

        pattern_data = sanitize_pattern_data(pattern_data)
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
        
        craft_terms = get_matching_craft_terms(pattern_data)
        
        return {
            "status": "success",
            "pattern_id": new_pattern_id,
            "data": pattern_data,
            "craft_terms": craft_terms,
            "is_cached": False
        }

    except HTTPException as he:
        raise he
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
        
        res = supabase.table("patterns").update({
            "pattern_data": sanitized_data
        }).eq("id", pattern_id).execute()

        if not res.data or len(res.data) == 0:
            raise HTTPException(status_code=404, detail="업데이트할 도안을 찾을 수 없습니다.")

        print(f"📝 [Updated] ID: {pattern_id}")
        return {
            "status": "success",
            "message": "도안이 성공적으로 수정되어 저장되었습니다.",
            "pattern_id": pattern_id
        }
    except Exception as e:
        print(f"❌ Error in PUT /api/pattern: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
