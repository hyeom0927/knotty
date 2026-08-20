# 데이터 모델

Supabase(PostgreSQL) 테이블 구조, 도안 JSON 스키마, 그리고 **기법 테이블 운영 규칙 · 코수 검증 알고리즘**을 정리한 문서입니다.

---

## 1. 테이블

### `patterns` — 생성된 도안

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid (PK) | 공유 링크 `?id=`에 그대로 쓰임 |
| `youtube_url` | text | 표시·공유용 표준 주소. `https://www.youtube.com/watch?v={id}` 형태로 정규화되어 저장됨 |
| `video_id` | text | 11자리 유튜브 ID. **캐시 키** — 동일 영상 요청 시 AI를 호출하지 않고 이 레코드를 반환 |
| `title` | text | `pattern_data.pattern_title` 우선, 없으면 영상 제목 |
| `thumbnail_url` | text | `img.youtube.com/vi/{id}/hqdefault.jpg` |
| `creator_id` | uuid (FK → creators) | ⚠️ 현재 항상 `null` — `ROADMAP.md` P0-2 참고 |
| `pattern_data` | jsonb | 도안 본문 (아래 2번) |

**추가 예정**

| 컬럼 | 용도 |
|---|---|
| `view_count` | int, 기본 0. 게시판·인기 도안 정렬용 (P3-2) |
| `created_at` | timestamptz. 최신순 정렬용 |

> **캐시는 `video_id`로 조회합니다.** 주소 원문을 키로 쓰면 `&t=1189s`, `&list=…`, `youtu.be/…`,
> shorts/live 주소가 전부 다른 영상으로 취급되어 **같은 영상에 AI를 2회씩 다시 호출**합니다.
> 지금은 어떤 형태로 들어와도 `extract_video_id()`가 같은 ID로 수렴시킨 뒤 조회합니다.
>
> 구버전에 주소 원문으로 저장된 레코드를 위해, `video_id` 조회가 비면 `youtube_url` 정확일치도 한 번 더 확인합니다.

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

**32건** 등록되어 있습니다 — 코바늘 약어 22 / 코바늘 용어 4 / 대바늘 약어 6.
시드 스크립트는 [`craft_terms_seed.sql`](craft_terms_seed.sql)입니다.

| 컬럼 | 설명 |
|---|---|
| `craft_type` | `crochet` / `knitting` |
| `entry_type` | `stitch` = 도안 약어 · `technique` = 용어사전 전용 (아래 참고) |
| `standard_code` | **유일한 기법 식별자.** `formula`에 등장하고 프롬프트에 주입되며 코수 검증이 매칭하는 키 |
| `kr_name` | 한국어 정식 명칭 (짧은뜨기, 한길긴뜨기 …) |
| `stitch_delta` | 이 기법 1개가 편물에 남기는 코 수. 코수 검증에 사용 (아래 4번) |
| `description` | 사전 설명. **실제 도안에서 쓰이는 다른 표기법도 여기에 서술** |
| `thumbnail_url` | 도안 기호 이미지 경로 (`symbols/<code>.svg`). [SYMBOLS.md](SYMBOLS.md) 참고 |
| `video_url` | 기법 설명 영상 (현재 비어 있음) |

#### 도안 기호는 SVG 이미지로 관리합니다

한국·일본이 쓰는 JIS 차트 기호는 **"T에 빗금 2개/3개"** 처럼 유니코드에 대응 글자가 없는 것이 대부분입니다.
그래서 28개(stitch 전부)를 24×24 SVG로 그려 `symbols/` 폴더에 두고, `thumbnail_url`로 연결합니다.
그리기 규칙은 [SYMBOLS.md](SYMBOLS.md)에 있습니다.

> 초기에는 유니코드 글자를 담는 `symbol_icon` 컬럼을 뒀지만 제거했습니다.
> 28개 중 8개만 표현 가능해 **예비값으로서 일관성이 없었고**, 같은 정보를 두 곳에서 관리하게 되기 때문입니다.

#### 코드 작명 규칙

`standard_code`는 **미국식 약어를 기본**으로 하되, 약어가 모호하거나 여러 형태로 통용되는 기법
(`puff`, `bobble`, `popcorn`, `crab`)은 **알아보기 쉬운 이름**을 씁니다.
`inc` / `dec`는 미국식 표준 약어이면서 기존 도안들이 이미 쓰고 있어 그대로 유지합니다.

실제 도안에 등장하는 다른 표기(`sc2tog`, `rev sc`, `puff st`, `2 sc in next st` …)와
영국식 표기(`sc`→`dc`, `dc`→`tr` …)는 **`description`에 문장으로** 적습니다.

> **`kr_short` · `us_abbr` · `uk_abbr`는 제거했습니다.**
> 세 컬럼 모두 코드가 한 번도 참조하지 않았고(0회), 값의 절반이 `standard_code`와 같아 혼란만 키웠습니다.
> 특히 `us_abbr`은 용어사전 4건에서 `null`이라 식별자가 될 수 없고,
> `dec`의 `us_abbr`인 `sc2tog`를 키로 삼으면 기존 도안의 `formula`(`dec` 사용)와 매칭이 끊깁니다.

> ⚠️ **`sl_st` 표기 주의**: `standard_code`는 언더스코어(`sl_st`)인데 도안 표기는 `sl st`(공백)입니다.
> 그래서 코드에서 `_normalize_code()`로 `[\s_]+`를 공백 하나로 통일해 같은 코드로 취급합니다.
> 정규화하지 않으면 **빼뜨기가 들어간 단이 전부 검증에서 빠집니다.**

#### `entry_type`을 나눈 이유

`craft_terms`는 **① AI에게 주는 허용 약어 목록**이자 **② 사람이 볼 용어사전**입니다.
배색·타원형 만들기·원형코 만들기·돗바늘 마무리처럼 **약어도 코수도 없는 "과정"**을 그냥 넣으면,
Pass 2 프롬프트에 섞여 들어가 AI가 `formula`에 `color_change` 같은 값을 적습니다.
`entry_type='technique'` 항목은 `build_terms_catalog_text()`가 프롬프트에서 제외합니다.

**추가 권장**

| 컬럼 | 용도 |
|---|---|
| `aliases` | text[] — 자막에 등장하는 한국어 표현들 (짧은뜨기, 짧은 뜨기, 단코 …) |

> `craft_type`이 이미 있으므로 별도 `needle_type` 컬럼은 필요 없습니다. 코드가 `craft_type`을 읽습니다.
> 다만 같은 약어를 코바늘·대바늘 양쪽에 등록하면 코수 검증기가 하나로 덮어씁니다 (아래 5번 참고).

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

-- ② 기법 사전 확장 (craft_type은 이미 있으므로 stitch_delta만 추가)
alter table craft_terms add column if not exists stitch_delta int;   -- 이 기법이 만드는 코 수

-- ③ 현재 등록된 15개 기법의 코수 (코드는 실제 standard_code 값 기준)
update craft_terms set stitch_delta = 1 where standard_code in ('ch','sc','hdc','dc','tr');
update craft_terms set stitch_delta = 2 where standard_code = 'inc';
update craft_terms set stitch_delta = 1 where standard_code in ('dec','k','p','yo','k2tog','ssk','co');
update craft_terms set stitch_delta = 0 where standard_code in ('sl_st','mr');

-- ④ 캐시 키 중복 방지 — 주소 원문이 아니라 video_id 기준
--    먼저 기존 중복을 확인한다. 결과가 있으면 아래 dedup을 돌린 뒤 인덱스를 건다.
select video_id, count(*) from patterns group by video_id having count(*) > 1;

-- (중복이 있을 때만) 가장 오래된 1건만 남기고 정리
delete from patterns p
using patterns q
where p.video_id = q.video_id
  and p.created_at > q.created_at;

create unique index if not exists patterns_video_id_key on patterns (video_id);
```

> `created_at` 컬럼이 아직 없다면 dedup 쿼리는 `p.id > q.id`로 바꾸거나,
> 중복 건을 직접 확인하고 지우세요.

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
- **`timestamps`**: ⚠️ **현재 전 도안이 `{start: 0, end: 0}`입니다.**
  자막은 `[123s] …` 형태로 들어오지만 **Pass 1 스키마에 타임스탬프 항목이 없어** 그 단계에서 버려집니다.
  Pass 2는 받은 값이 없으니 0으로 채웁니다. 복구 계획은 [ROADMAP.md P2-0](ROADMAP.md) 참고.
- **`materials.yarn`**: 현재 문자열 하나라 **굵기·게이지가 담기지 않습니다.**
  게이지가 없으면 완성 크기가 달라지므로 객체 배열로 바꿀 예정입니다 (ROADMAP.md P2-4).
  이때 **모르는 게이지를 지어내지 않도록** `source: video | inferred`를 함께 저장합니다.
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

1. 요청 시작 시 `craft_terms`에서 `standard_code` + `kr_name` 전체를 조회 (프로세스 캐싱)
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
