import json
import re
from google import genai
from google.genai import types
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

# 1. Gemini API 키 입력
API_KEY = "AIzaSyA0JFplnGl9VWQ-efwGUVCNiXOPn3PvPto"

# [자동화 1] 유튜브 URL에서 영상 ID(11자리) 추출 함수
def extract_video_id(url):
    regex = r"(?:v=|\/([0-9A-Za-z_-]{11}).*|youtu\.be\/)([0-9A-Za-z_-]{11})"
    match = re.search(regex, url)
    if match:
        return match.group(1) or match.group(2)
    return url

# [자동화 2] yt-dlp를 이용해 영상 제목 및 설명란 수집 함수
def get_youtube_metadata(url):
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', '')
        description = info.get('description', '')
        return title, description

# [자동화 3] 자막 및 타임스탬프 가져오기 (최신/구버전 youtube-transcript-api 호환)
def get_youtube_transcript(video_id):
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=['ko', 'en'])
        transcript_list = fetched.to_raw_data()
    except Exception:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
    
    formatted_transcript = ""
    for item in transcript_list:
        start = int(item['start'])
        text = item['text']
        formatted_transcript += f"[{start}s] {text}\n"
    return formatted_transcript

# [전체 파이프라인 통합 함수]
def generate_crochet_pattern_from_url(youtube_url):
    print("⏳ 1. 유튜브 URL 분석 및 영상 ID 추출 중...")
    video_id = extract_video_id(youtube_url)
    
    print("⏳ 2. 영상 제목 및 설명란(재료 정보) 자동으로 수집 중...")
    title, description = get_youtube_metadata(youtube_url)
    
    print("⏳ 3. 영상 자막 및 타임스탬프 추출 중...")
    transcript = get_youtube_transcript(video_id)
    
    print("⏳ 4. Gemini AI 분석 및 코바늘 도안 JSON 생성 중...")
    system_prompt = """
    당신은 코바늘 및 대바늘 뜨개질 전문가이자 데이터 정형화 에이전트입니다.
    무작위로 제공되는 유튜브 비디오 자막 및 설명란 텍스트를 분석하여, 영상의 뜨개질 종류를 파악하고 반드시 아래의 JSON 구조에 맞춰 범용적인 도안 데이터를 생성하세요.

    [필수 JSON 출력 구조]
    {
      "materials": {
        "yarn": "교정된 실 이름 및 소요량",
        "needle": {
          "type": "바늘 종류 (예: 코바늘, 대바늘)",
          "size": "호수 및 굵기 (예: 5/0호(3.0mm), 4.5mm)"
        },
        "accessories": ["단수링, 돗바늘 등 부자재 리스트"]
      },
      "total_rows": 총 단수 (정수형 숫자),
      "pattern_steps": [
        {
          "step_number": 1,
          "step_name": "기초 코 잡기 (Foundation Chain / Cast on)",
          "formula": "도안 약어 (미국식 표준)",
          "instruction": "상세 설명",
          "total_stitches": 코 수 (숫자 또는 null),
          "timestamps": { "start": 초, "end": 초 }
        }
      ]
    }

    [절대 준수: 데이터 범용 교정 및 계산 규칙]
    1. 바늘 정보 구조화: 사용되는 바늘이 '코바늘'인지 '대바늘'인지 영상 문맥(바늘, hook, needle 등)을 통해 파악하여 `needle.type`에 명시하고, `needle.size`에는 호수와 굵기(mm)를 함께 기재하세요.
    2. 실 이름 자동 교정 (STT 오류 보정): 유튜브 음성 인식 특성상 뜨개실 고유명사 오타가 매우 흔합니다 (예: '실 코트 포' -> '코튼4', '마크 라면' -> '마크라메'). 오타가 감지되면, 직역하거나 가상의 단어(예: Silk Coat 4)를 창조하지 말고 실제 시중에 판매되는 뜨개실 이름으로 추론하여 교정하세요.
    3. 스펙 자동 추론: 영상에서 실 이름만 언급되고 바늘 호수나 소요량이 누락된 경우, 교정된 실의 '표준 권장 바늘 호수'와 해당 소품에 맞는 '일반적인 소요량'을 당신의 지식베이스를 바탕으로 추론하여 채워 넣으세요.
    4. 총 단수(total_rows) 산출: 코바늘의 '기초 사슬'이나 대바늘의 '기초 코'를 무조건 '1단'으로 산정합니다. 이후 반복되는 본판 무늬 단수를 모두 합산하여 최종 총 단수를 루트 레벨의 `total_rows`에 정수로 기재하세요.
    5. 예외 처리: 추론조차 불가능한 명확하지 않은 정보만 "미기재" 또는 null 처리하세요.
    """

    user_content = f"""
    [영상 제목]
    {title}

    [영상 설명란]
    {description}

    [영상 자막 및 타임스탬프]
    {transcript}
    """

    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",  # 👈 1.5-flash 대신 최신 gemini-2.5-flash로 수정
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
        ),
    )

    return json.loads(response.text)

if __name__ == "__main__":
    target_url = "https://www.youtube.com/watch?v=r5PXSJvEmdo&t=6057s"
    pattern_json = generate_crochet_pattern_from_url(target_url)
    
    print("\n================ [생성 완료된 도안 데이터] ================\n")
    print(json.dumps(pattern_json, ensure_ascii=False, indent=2))
