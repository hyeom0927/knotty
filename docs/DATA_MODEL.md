# 데이터 모델

Supabase(PostgreSQL) 테이블 구조, 도안 JSON 스키마, 그리고 **기법 테이블 운영 규칙 · 코수 검증 알고리즘**을 정리한 문서입니다.

---

## 1. 테이블

### `patterns` — 생성된 도안

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid (PK) | 공유 링크 `?id=`에 그대로 쓰임 |
| `youtube_url` | text | **캐시 키.** 동일 URL 요청 시 AI를 호출하지 않고 이 레코드를 반환 |
| `video_id` | text | 11자리 유튜브 ID |
| `title` | text | `pattern_data.pattern_title` 우선, 없으면 영상 제목 |
| `thumbnail_url` | text | `img.youtube.com/vi/{id}/hqdefault.jpg` |
| `creator_id` | uuid (FK → creators) | ⚠️ 현재 항상 `null` — `ROADMAP.md` P0-2 참고 |
| `pattern_data` | jsonb | 도안 본문 (아래 2번) |

**추가 예정**

| 컬럼 | 용도 |
|---|---|
| `view_count` | int, 기본 0. 게시판·인기 도안 정렬용 (P3-2) |
| `created_at` | timestamptz. 최신순 정렬용 |

> `youtube_url`을 캐시 키로 쓰므로 **유니크 인덱스**가 있어야 합니다.
> 같은 영상이라도 `&t=6057s` 같은 파라미터가 붙으면 다른 URL로 취급되어 중복 생성됩니다.
> → 저장·조회 시 `video_id` 기준으로 정규화하는 편이 안전합니다.

### `creators` — 유튜브 채널 (원작자)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid (PK) | |
| `channel_name` | text | 화면에 표시되는 채널명 |
| `channel_url` | text **UNIQUE** | 중복 수집 방지 키. `upsert(on_conflict="channel_url")` |

**추가 예정**

| 컬럼 | 용도 |
|---|---|
| `shop_url` | 채널 운영자의 쇼핑몰 (바늘이야기·앵콜스·솜솜뜨개 등). 실 구매 링크 생성에 사용 |
| `pattern_shop_url` | 도안 판매처 |

> **중복 수집 금지 규칙**: 채널 식별자는 반드시 `channel_url`입니다. 채널명은 변경될 수 있으므로 키로 쓰지 않습니다.
> 가능하면 `youtube.com/channel/UC...` 형태의 **채널 ID URL**로 정규화해 저장하세요. `@핸들`은 바뀔 수 있습니다.

### `craft_terms` — 기법 사전 (마스터 테이블)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `standard_code` | text | 표준 영문 약어 (`ch`, `sc`, `inc`, `dec`, `hdc`, `dc`, `mr`, `sl st` …) |
| `kr_formal` | text | 한국어 정식 명칭 (사슬뜨기, 짧은뜨기 …) |
| `video_url` | text | 기법 설명 영상 |

**추가 권장**

| 컬럼 | 용도 |
|---|---|
| `needle_type` | `코바늘` / `대바늘` / `공통` — 바늘 종류에 맞는 기법만 노출 |
| `stitch_delta` | 이 기법이 만들어내는 코 수. 코수 검증에 사용 (아래 4번) |
| `aliases` | text[] — 자막에 등장하는 한국어 표현들 (짧은뜨기, 짧은 뜨기, 단코 …) |

### `craft_terms_pending` — 신규 기법 등록 큐 (신설)

AI가 테이블에 없는 기법을 만났을 때 쌓이는 곳입니다. 운영자가 확인 후 `craft_terms`로 승격합니다.

| 컬럼 | 설명 |
|---|---|
| `raw_text` | 자막/도안에 등장한 원문 |
| `occurrence_count` | 등장 횟수 — 많이 나온 것부터 처리 |
| `sample_pattern_id` | 어느 도안에서 나왔는지 |
| `status` | `pending` / `approved` / `rejected` |

### `reports` — 오류 보고 (신설)

| 컬럼 | 설명 |
|---|---|
| `pattern_id` | 대상 도안 |
| `step_ref` | 문제가 된 파츠·단 (선택) |
| `message` | 사용자가 남긴 내용 |

---

## 1-1. Supabase에 적용해야 할 SQL

아래는 **아직 실행되지 않았습니다.** 백엔드 코드는 이 테이블·컬럼이 없어도 정상 동작하지만
(조회 실패 시 경고만 남기고 넘어감), 실행해야 P1 기능이 온전히 작동합니다.

```sql
-- ① 미등록 기법 큐 (없으면 unknown_terms가 그냥 버려짐)
create table if not exists craft_terms_pending (
  id                uuid primary key default gen_random_uuid(),
  raw_text          text not null unique,
  occurrence_count  int  not null default 1,
  sample_pattern_id uuid references patterns(id) on delete set null,
  status            text not null default 'pending',   -- pending | approved | rejected
  created_at        timestamptz not null default now()
);

-- ② 기법 사전 확장 (없으면 기본 코수 테이블만 사용)
alter table craft_terms add column if not exists needle_type  text;  -- 코바늘 | 대바늘 | 공통
alter table craft_terms add column if not exists stitch_delta int;   -- 이 기법이 만드는 코 수

-- ③ 기본 기법의 코수 등록 (예시 — 사전에 이미 있는 코드에만 적용됨)
update craft_terms set stitch_delta = 1 where standard_code in ('sc','hdc','dc','tr','dtr');
update craft_terms set stitch_delta = 2 where standard_code = 'inc';
update craft_terms set stitch_delta = 1 where standard_code = 'dec';
update craft_terms set stitch_delta = 0 where standard_code in ('sl st','mr');

-- ④ 캐시 키 중복 방지 (같은 영상이 여러 건 저장되는 것을 막음)
create unique index if not exists patterns_youtube_url_key on patterns (youtube_url);
```

> `stitch_delta`를 채워두면 사전에 새 기법을 등록하는 것만으로 **코수 검증 범위가 자동으로 넓어집니다.**
> 값이 없는 기법은 검증에서 제외(`skipped`)되므로, 틀린 경고가 뜨는 일은 없습니다.

---

## 2. `pattern_data` JSON 구조

Pass 2가 최종 반환하는 형태입니다.

```json
{
  "pattern_title": "작품 이름",
  "materials": {
    "yarn": "실 이름 및 소요량",
    "needle": { "type": "코바늘", "size": "3/0호(2.3mm)" },
    "accessories": ["단수링", "돗바늘"]
  },
  "total_rows": 36,
  "parts": [
    {
      "part_name": "몸판 (2장 제작)",
      "steps": [
        {
          "step_number": 1,
          "step_name": "1단",
          "formula": "ch 2, dc 12",
          "instruction": "기둥사슬 2개를 뜨고 한길긴뜨기 12개를 뜹니다.",
          "total_stitches": 12,
          "timestamps": { "start": 0, "end": 0 }
        }
      ]
    }
  ],
  "metadata": {
    "channel_name": "...", "channel_url": "...",
    "thumbnail_url": "...", "youtube_url": "..."
  }
}
```

### 필드 규칙

- **`parts` vs `pattern_steps`**: 현재 코드는 두 형태를 모두 렌더링합니다. `parts`(파츠 구분 있음)가 표준이고, `pattern_steps`는 초기 스키마의 잔재입니다. 신규 도안은 `parts`로 통일하세요.
- **`part_name`의 수량 정보**: "몸판 (2장 제작)"처럼 **몇 장을 떠야 하는지** 반드시 보존합니다. Pass 1·2 프롬프트 모두 이를 명시적으로 요구합니다.
- **`total_rows`**: step 배열의 개수가 아니라 **가장 단수가 많은 주요 파츠의 최대 단수**입니다.
- **`formula` 표기 규칙** (Pass 2 프롬프트에 명시됨)
  - 약어와 숫자 사이 공백 1칸: `ch 1, sc 3, inc 1` (⭕) / `ch1, sc3` (❌)
  - 반복은 괄호 + `x 횟수`: `(sc 2, inc 1) x 4`
  - 구분자는 쉼표 + 공백
  - "(does not count as st)", "(코로 세지 않음)" 같은 부연설명 괄호는 금지 — 서버의 `clean_pattern_text()`가 한 번 더 걸러냅니다
- **조립·마무리 단계**: 지퍼 달기, D링 연결 등 비뜨개 과정은 별도 파츠로 분리하고 `total_stitches: 0`.

---

## 3. 기법 테이블 참조 규칙

> **원칙: 기법은 항상 `craft_terms` 테이블을 기준으로 호출한다.**
> AI가 자유롭게 만들어낸 약어를 사후에 매칭하는 방식(현재)에서, **허용 목록을 미리 주는 방식**으로 전환합니다.

처리 순서:

1. 요청 시작 시 `craft_terms`에서 `standard_code` + `kr_formal` 전체를 조회 (프로세스 캐싱)
2. **Pass 2 프롬프트에 허용 약어 목록을 주입** — "이 목록에 있는 약어만 `formula`에 사용할 것"
3. 목록에 없는 기법을 만나면 → `formula`에 임의 약어를 만들지 말고 `unknown_terms: ["원문"]`에 담도록 지시
4. 응답의 `unknown_terms` → `craft_terms_pending`에 누적
5. 화면의 "사용한 기법" 표는 `craft_terms` 조인 결과로 렌더링

이 구조의 이점:
- 도안에 쓰이는 약어가 사전과 **항상 일치** → 용어사전 페이지, 기법 영상 링크가 빠짐없이 연결됨
- 새 기법이 등장해도 조용히 유실되지 않고 큐에 남음
- `stitch_delta`가 테이블에 있으므로 아래 코수 검증이 자동으로 확장됨

---

## 4. 코수 검증 알고리즘

> **목적: AI가 계산한 `total_stitches`를 그대로 믿지 않는다.**
> `formula`를 직접 파싱해 코수를 다시 세고, 값이 다르면 **사용자에게 경고를 띄운다.** 자동 교정은 하지 않습니다.

### 기법별 코 수 (`stitch_delta`)

| 약어 | 만들어내는 코 수 | 비고 |
|---|:---:|---|
| `sc`, `hdc`, `dc`, `tr` | 1 | 기본 뜨기 |
| `inc` | 2 | 한 코에 두 번 → 1코 증가 |
| `dec` | 1 | 두 코를 하나로 → 1코 감소 |
| `ch` | 0 또는 N | 아래 별도 규칙 |
| `sl st` | 0 | 원형 연결용. 코수에 포함하지 않는 것을 기본으로 함 |
| `mr` | 0 | 매직링 자체는 코가 아님 |

**`ch` 판별 규칙** — 행 맨 앞의 `ch`는 기둥사슬일 수도, 기초 사슬일 수도 있습니다.
"몇 단째인가"가 아니라 **뒤에 실제로 뜬 코가 있는지**로 구분합니다.

| 예시 | 계산 | 이유 |
|---|:---:|---|
| `ch 20` | 20 | 뒤가 비어 있음 → 사슬 자체가 그 단의 결과 (기초 사슬) |
| `ch 20, sl st 1` | 20 | 뒤에 코를 만드는 기법이 없음 → 기초 사슬 |
| `ch 21, sc 20` | 20 | 뒤에 코가 있음 → 그 사슬 위에 뜬 것이므로 사슬은 세지 않음 |
| `ch 1, sc 20` | 20 | 기둥사슬 |
| `mr, ch 1, sc 6` | 6 | 매직링을 건너뛰고 그다음 `ch`를 기둥사슬로 판정 |
| `(dc 2, ch 1) x 5` | 15 | 행 중간의 `ch`는 코수에 포함 |

> "파츠의 첫 단이면 기초 사슬" 같은 위치 기반 규칙은 **매직링으로 시작하는 원형 도안에서 오탐**을 냅니다.
> (`mr, ch 1, sc 6`을 7코로 계산하는 문제) 그래서 위치가 아닌 문맥으로 판정합니다.

### 파싱 절차

```
1. formula를 쉼표 단위로 토큰화 (괄호 안은 하나의 그룹으로 유지)
2. "(...) x N" 그룹 → 내부 합계 × N
3. 각 토큰을 "약어 + 숫자"로 분해
4. 위 표의 stitch_delta를 곱해 누적
5. parsed_total 과 step.total_stitches 를 비교
```

### 판정

| 조건 | 결과 |
|---|---|
| 표에 없는 약어가 하나라도 있음 | `skipped` — **검증하지 않음** (틀린 경고를 내느니 침묵) |
| 조립·마무리 파츠 (`total_stitches: 0`) | `skipped` |
| `parsed_total == total_stitches` | `ok` |
| 값이 다름 | `mismatch` — step에 `{ expected, parsed }` 부착 |

```json
"validation": { "status": "mismatch", "expected": 24, "parsed": 22 }
```

### 추가 검사: 단 간 연속성

늘림·줄임이 없는 단인데 앞 단과 코수가 달라지면 의심 신호입니다.
`inc` / `dec` / **행 중간의 `ch`** 가 없는 단의 `total_stitches`가 직전 단과 다르면 `mismatch`(`reason: "continuity"`)로 표시합니다.

> ⚠️ **연쇄 오탐 방지**: 검증에 걸린 단의 코수는 다음 단의 비교 기준으로 쓰지 않습니다.
> 그렇게 하지 않으면 한 단이 틀렸을 때 뒤따르는 멀쩡한 단이 전부 경고로 뒤덮입니다.

### UI 처리

- 해당 행에 ⚠️ 배지 + "코수 확인 필요" 툴팁
- 도안 전체가 아니라 **문제가 된 단만** 표시 — 나머지 신뢰도를 깎지 않기 위함
- 사용자가 편집 모드로 직접 고칠 수 있게 (P0-3 저장 버그 수정 후)

---

## 5. 바늘 종류

`materials.needle.type`은 **`"코바늘"` 또는 `"대바늘"` 두 값만 허용**합니다.

- Pass 2 프롬프트에서 두 값 중 하나로 강제
- 서버에서 한 번 더 검증: 다른 값이면 `formula`에 등장하는 약어로 추론 (`sc`/`dc`/`mr` 계열 → 코바늘, `k`/`p` 계열 → 대바늘)
- 바늘 종류는 향후 **기법 사전 필터링**(코바늘 도안에 대바늘 기법이 섞이지 않게)과 **바늘 구매 링크 생성**에 쓰입니다
