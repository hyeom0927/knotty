# Knotty 🧶

뜨개질 유튜브 영상 링크 하나로, 영상 속 뜨개 과정을 **단(Row)별 표로 정리해 보여주는 웹 서비스**입니다.

영상을 보면서 "방금 몇 단이었지?", "이 기법이 뭐였지?" 하고 되감기를 반복하는 초보 뜨개러를 위한 도구입니다.
자막과 설명란을 AI가 읽어 단수 · 코수 · 기법 약어를 표로 재구성하고, 기법마다 참고 영상과 준비물 구매처를 함께 붙여줍니다.

> **포지셔닝**: 뜨개질계의 [해먹으리]. 도안을 파는 서비스가 아니라, **영상 시청을 돕는 요약·정리 도구**입니다.
> 도안의 저작권은 원작자(유튜버)에게 있으며, Knotty는 원본 영상·채널·판매 링크로 트래픽을 되돌려 보냅니다.
> 자세한 원칙은 [docs/POSITIONING.md](docs/POSITIONING.md)를 참고하세요.

---

## 지금 어디까지 되어 있나

MVP 프로토타입이 동작 중입니다. 유튜브 링크 → 도안 표 → PNG/PDF 저장 → 공유 링크까지 한 사이클이 완성되어 있습니다.

기능별 구현 현황과 미구현 목록은 **[docs/FEATURES.md](docs/FEATURES.md)**,
앞으로의 작업 순서는 **[docs/ROADMAP.md](docs/ROADMAP.md)** 에 정리되어 있습니다.

---

## 아키텍처

```
[사용자 브라우저]
   index.html  (정적 페이지 / GitHub Pages)
        │  fetch
        ▼
[FastAPI 백엔드]  main.py       (Render)
        ├─ 유튜브 페이지 파싱 ──── 제목 / 설명란 / 채널명
        ├─ Supadata API ────────── 자막 (Render IP 차단 우회용)
        ├─ Gemini API ──────────── Pass 1 추출 → Pass 2 규격화
        └─ Supabase ────────────── patterns / creators / craft_terms
```

| 파일 | 역할 |
|---|---|
| `main.py` | **현재 운영 중인 백엔드.** FastAPI 앱, 유튜브 수집, Gemini 2-Pass 호출, Supabase 저장 |
| `prompts.py` | Pass 1(추출) / Pass 2(규격화) 시스템 프롬프트 |
| `index.html` | 프론트엔드 전체. Tailwind CDN + 바닐라 JS 단일 파일 |
| `app.py` | ⚠️ 초기 프로토타입(yt-dlp 기반). 현재 미사용 — 정리 대상 |
| `requirements.txt` | 파이썬 의존성 |

### AI 파이프라인 (2-Pass)

한 번에 처리하면 단(Row)이 뭉개져서 두 단계로 나눴습니다.

1. **Pass 1 — 추출**: 자막에서 잡담을 걷어내고 단별 뜨개 동작을 *보존*합니다. "몸판 뜨기" 같은 뭉뚱그린 요약을 금지하는 것이 핵심 규칙입니다.
2. **Pass 2 — 규격화**: Pass 1 결과를 표준 영문 약어(`ch`, `sc`, `inc`, `dec`, `hdc`, `dc`, `mr`, `sl st`)로 변환하고, 코수·총 단수를 계산해 최종 JSON 스키마로 다듬습니다.

두 Pass 모두 `response_mime_type="application/json"`으로 JSON을 강제하고, 503/429 발생 시 지수 백오프로 3회까지 재시도합니다.

---

## 로컬 실행

```bash
cd ~/Documents/knotty
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 환경변수 설정 (아래 표 참고)
export GEMINI_API_KEY=...
export SUPABASE_URL=...
export SUPABASE_KEY=...
export SUPADATA_API_KEY=...

uvicorn main:app --reload --port 8000
```

프론트엔드는 정적 파일이므로 그대로 열면 됩니다. 단, `index.html`의 `API_BASE`가 운영 서버(`https://knotty-paid.onrender.com`)로 고정되어 있으므로 로컬 백엔드를 붙이려면 그 값을 `http://localhost:8000`으로 바꿔야 합니다.

```bash
python3 -m http.server 5500   # 이후 http://localhost:5500/index.html
```

### 환경변수

| 이름 | 필수 | 기본값 | 설명 |
|---|:---:|---|---|
| `GEMINI_API_KEY` | ✅ | — | Google AI Studio 발급 키 |
| `SUPABASE_URL` | ✅ | — | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | ✅ | — | Supabase API 키 |
| `SUPADATA_API_KEY` | ✅ | — | 자막 수집용. 없으면 로컬 fallback만 동작 (Render에서는 실패) |
| `GEMINI_MODEL_PASS1` | ⬜ | `gemini-3.7-flash` | 자막 → 단별 추출 |
| `GEMINI_MODEL_PASS2` | ⬜ | `gemini-3.1-flash-lite` | 규격화 · 코수 계산 |
| `GEMINI_MODEL` | ⬜ | — | 위 둘을 지정하지 않았을 때의 공통 fallback |

#### Pass별로 모델을 나누는 이유

무료 티어의 호출 한도는 **모델 단위로 잡히고 프로젝트 단위로 적용**됩니다.
두 Pass에 서로 다른 모델을 쓰면 **일일 한도 버킷이 둘로 나뉘어** 하루에 만들 수 있는 도안 수가 늘어납니다.

동시에 품질 배분도 맞아떨어집니다.

- **Pass 1**은 긴 자막에서 단을 하나도 빠뜨리지 않아야 합니다. 누락된 단은 **조용히 사라지고 복구할 방법이 없으므로** 좋은 모델을 씁니다.
- **Pass 2**의 산술 오류는 서버의 코수 검증기가 잡아내므로, 한도 여유가 큰 모델을 써도 안전합니다.

서버 기동 시 로그에 실제 적용된 모델이 찍힙니다: `🧶 Knotty 기동 — Pass 1: … / Pass 2: …`

> **429가 발생하면**: 로그에 `🚫 [모델명] 호출량 한도 응답:` 과 함께 위반한 quota 이름이 그대로 남습니다.
> 이름에 `PerDay`가 들어 있으면 일일 한도(재시도 무의미 → 사용자에게 429 안내),
> `PerMinute`면 분당 한도로 보고 지수 대기 후 자동 재시도합니다.

> **자막 수집에 대하여**: Render의 서버 IP는 유튜브에서 차단되어 `youtube-transcript-api`가 동작하지 않습니다.
> 그래서 운영 환경은 Supadata API를 쓰고, 라이브러리 호출은 로컬 전용 fallback으로만 남겨두었습니다.

---

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/generate` | `{"youtube_url": "..."}` → 도안 생성. 동일 URL이 이미 있으면 DB 캐시를 즉시 반환 |
| `GET` | `/api/pattern/{id}` | 저장된 도안 단건 조회 (`?id=` 공유 링크가 이걸 씁니다) |
| `PUT` | `/api/pattern/{id}` | 사용자가 수정한 도안 저장 |

응답에는 `pattern_data`(도안 본문), `craft_terms`(사용된 기법 목록), `creators`(채널 정보)가 함께 담깁니다.
데이터 구조와 DB 스키마는 [docs/DATA_MODEL.md](docs/DATA_MODEL.md)를 참고하세요.

---

## 배포

정식 상용 서비스가 아니라 **GitHub 기반의 가벼운 운영**을 전제로 합니다.

- 프론트엔드: GitHub Pages (저장소 `hyeom0927/knotty`)
- 백엔드: Render (`knotty-paid.onrender.com`)
- DB: Supabase (PostgreSQL)

---

## 문서

| 문서 | 내용 |
|---|---|
| [docs/FEATURES.md](docs/FEATURES.md) | 기능 명세 + 구현/미구현 Gap 분석 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 우선순위별 작업 계획 |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | DB 스키마, 도안 JSON 구조, 기법 테이블·코수 검증 규칙 |
| [docs/POSITIONING.md](docs/POSITIONING.md) | 저작권 원칙, 카피 가이드, 수익화 방향, 경쟁사 분석 프레임 |
