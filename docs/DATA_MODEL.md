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
| `creator_id` | uuid (FK → creators) | ✅ 정상 수집 중 |
| `pattern_data` | jsonb | 도안 본문 (아래 2번) |
| `created_at` | timestamptz | 최신순 정렬 |
| `view_count` | int (기본 0) | `GET /api/pattern/{id}` 때 1씩 증가. 인기순 정렬에 사용 |
| `is_hidden` | bool | 참이면 목록(`GET /api/patterns`)에서 제외. 창작자 opt-out 요청용 |

> **조회수는 읽고 더해 쓰는 방식입니다.** 동시 요청이 겹치면 몇 건 샙니다.
> 정확히 세려면 원자적 증가 함수(RPC)가 필요한데, 인기 정렬에 쓰는 값이라
> 몇 건의 오차가 순위를 바꾸지 않아 감수하고 있습니다. 실패해도 조회 자체는 막지 않습니다.

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
| `channel_id` | text | `UC` + 22자 불변 ID |
| `channel_handle` | text | `@핸들` (표시용) |
| `shop_url` | text | 채널 운영자의 쇼핑몰. **설명란에서 판매 링크를 찾으면 자동으로 기억합니다** |
| `pattern_shop_url` | text | 도안 판매처 |
| `opt_out` | bool | 창작자가 수집 거부를 요청한 채널 |

> **중복 수집 금지 규칙**: 채널 식별자는 반드시 `channel_url`입니다. 채널명은 변경될 수 있으므로 키로 쓰지 않습니다.
>
> ⚠️ **`UC` 형식을 검증한 뒤에만 `/channel/` 경로를 씁니다.** (2026-08-22 버그 수정)
> Supadata가 `channel.id`에 `@핸들`을 넣어 주는 경우가 있는데, 그대로 붙이면
> `youtube.com/channel/@banul.official`이라는 **열리지 않는 주소**가 됩니다.
> `channel_url`이 중복 방지 키라서 같은 채널이 두 행으로 갈라졌습니다(정리 완료).
> 핸들만 있으면 `youtube.com/@handle` 형태로 만듭니다.
>
> **채널 쇼핑몰은 한 번 알면 계속 씁니다.** 창작자가 링크를 매 영상에 달지는 않지만
> (실측 7건 중 3건은 없었음) 가게는 채널마다 하나이므로, 링크가 없는 영상에서도
> `shop_url`로 원작자 가게를 안내합니다. 판매자별 방이 있는 주소
> (`sevy.co.kr/minishop/cyber8912`)는 그 경로까지 보존합니다 — 호스트만 남기면
> 플랫폼 본사 몰로 보내게 됩니다.

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

### `yarn_specs` — 실 사전 (신설, 미적용)

영상에는 게이지가 거의 나오지 않습니다(실측 7건 중 **0건**). 실 이름으로 이 표를 찾아 보완합니다.

| 컬럼 | 설명 |
|---|---|
| `name` | 대표 이름 (예: 메리노프린트) |
| `aliases` | text[]. 자막에서 달리 불리는 이름 |
| `brand` · `craft_type` | 판매처 · crochet/knit |
| `weight_class` · `needle_size` | 굵기 등급 · 권장 바늘 호수 |
| `ball_weight` · `ball_length` | 1볼 중량 · 길이 |
| `gauge_label` | **실 라벨 기준** 게이지. 코바늘 실은 대개 없음 → `null` |
| `source_url` | 이 값을 확인한 페이지. 나중에 되짚을 수 있게 남깁니다 |

> ⚠️ **`gauge_label`은 그 도안의 게이지가 아닙니다.** 메리노프린트는 라벨이 20코 × 27단인데
> 같은 실로 뜬 고양이귀 비니 도안은 22코 × 31단입니다. `pattern_data`에서도
> `yarn[].gauge`(도안)와 `yarn[].spec.gauge_label`(라벨)을 다른 자리에 담습니다.
>
> **코바늘 실은 게이지를 아예 공개하지 않는 것이 정상입니다.** 도안마다 다르기 때문입니다.
> 그런 실은 `needle_size`와 `ball_weight`/`ball_length`가 대체 실을 고르는 근거가 됩니다.
>
> 값은 **확인한 페이지가 있는 것만** 넣고 모르면 `null`로 둡니다.
> 사전에 없는 실은 서버 로그에 `🧵 사전에 없는 실: …`로 남습니다.

SQL은 [yarn_specs.sql](yarn_specs.sql)에 있습니다.

---

## 1-1. Supabase에 적용해야 할 SQL

> **적용 현황 (2026-08-24 확인)**
>
> | SQL | 상태 |
> |---|---|
> | [schema_migration.sql](schema_migration.sql) — `video_id`·`view_count`·`is_hidden`·`creators` 확장 | ✅ 적용됨 |
> | [craft_terms_seed.sql](craft_terms_seed.sql) / [craft_terms_update.sql](craft_terms_update.sql) — 기법 사전 36건 | ✅ 적용됨 |
> | `craft_terms_pending` · `reports` | ✅ 적용됨 |
> | [yarn_specs.sql](yarn_specs.sql) — 실 사전 | ⬜ **미적용** (이 기능만 꺼져 있음) |
>
> 백엔드는 테이블이 없어도 정상 동작합니다(조회 실패 시 경고만 남기고 넘어감).
> 아래는 참고용 원문입니다.

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

Pass 2가 만든 뒤 **서버가 몇 가지를 더 얹어** 저장하는 형태입니다.
AI가 만드는 것과 서버가 만드는 것을 구분해 두는 것이 중요합니다 — 서버가 얹는 값은
사용자 편집으로 바뀌면 안 되고, AI가 지어낼 수도 없어야 하기 때문입니다.

```json
{
  "pattern_title": "작품 이름",
  "materials": {
    "yarn": [
      {
        "name": "오메가",
        "color": "186번 귤색",
        "weight": "중세사",
        "amount": "50g 1볼",
        "gauge": null,
        "source": "video",
        "spec": {
          "brand": "바늘이야기",
          "needle_size": "4/0~5/0호",
          "ball_weight": "30g±3g",
          "ball_length": "60m±5m",
          "gauge_label": "10x10cm = 20코 × 27단",
          "source_url": "https://…"
        }
      }
    ],
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
          "timestamps": { "start": 84, "end": 0 },
          "validation": { "status": "mismatch", "reason": "total_stitches",
                          "expected": 12, "parsed": 14 }
        }
      ]
    }
  ],
  "shop_links": {
    "pattern": [{ "url": "https://…", "label": "🍭도안만 구매는 여기서🍭" }],
    "supply":  [{ "url": "https://…", "label": "메리노프린트 실 구매 링크" }],
    "channel": [{ "url": "https://…", "label": "앵콜스 쇼핑몰" }],
    "search":  [{ "url": "https://search.shopping.naver.com/…", "label": "롤리 코튼" }]
  },
  "validation_summary": { "mismatch_count": 0 },
  "metadata": {
    "channel_name": "…", "channel_url": "…",
    "thumbnail_url": "…", "youtube_url": "…"
  }
}
```

### 누가 만드는 값인가

| 필드 | 만드는 주체 | 비고 |
|---|---|---|
| `pattern_title` · `parts` · `formula` · `instruction` · `total_stitches` | **Pass 2 (AI)** | 사용자가 화면에서 고칠 수 있음 |
| `materials.yarn[].name/color/weight/amount/gauge/source` | **Pass 2 (AI)** | 이름은 사용자가 고칠 수 있음 |
| `timestamps.start` | **Pass 1 (자막) → Pass 2 전달** | 서버가 보충·검증. 아래 참고 |
| `materials.yarn[].spec` | **서버** (`yarn_specs` 사전) | 실 라벨 기준 정보 |
| `shop_links` | **서버** (설명란 파싱) | ⚠️ 사용자 편집으로 바뀌지 않음 |
| `validation` · `validation_summary` | **서버** (코수 검증기) | 저장할 때마다 다시 계산 |
| `metadata` | **서버** (유튜브 수집) | |

> **`shop_links`는 저장된 값이 항상 이깁니다.** `PUT /api/pattern/{id}`에 인증이 없는데
> `pattern_data`가 브라우저를 왕복하므로, 그대로 두면 누구나 "정식 도안 구매하기" 버튼의
> 주소를 바꿔치기할 수 있습니다.

### 필드 규칙

- **`parts` vs `pattern_steps`**: 두 형태를 모두 렌더링합니다. `parts`가 표준이고
  `pattern_steps`는 초기 스키마의 잔재입니다. 저장된 도안은 전부 `parts`입니다.
- **`part_name`의 수량 정보**: "몸판 (2장 제작)"처럼 **몇 장을 떠야 하는지** 반드시 보존합니다.
- **`total_rows`**: step 배열의 개수가 아니라 **가장 단수가 많은 주요 파츠의 최대 단수**입니다.
  단 이름이 "N단"이 아닌 도안(대바늘의 "코잡기 및 고무뜨기" 등)에서는 `0`이 나오기도 합니다.
- **`timestamps.start`** — 그 단의 설명이 시작되는 **영상 초**. 없으면 `0`.
  - 시각의 출처는 **자막뿐**이고 자막을 보는 것은 Pass 1뿐입니다.
    Pass 2가 필드를 흘리면 기능이 조용히 죽으므로, 서버의 `graft_pass1_timestamps()`가
    Pass 1이 준 값을 **Pass 2가 비워 둔 자리에만** 채웁니다.
  - `validate_timestamps()`가 **영상 길이를 넘거나 앞 단보다 빠른 값을 지웁니다.**
    틀린 시각으로 보내는 것은 링크가 없는 것보다 나쁩니다.
  - `end`는 쓰지 않습니다. 항상 `0`입니다.
- **`materials.yarn`은 객체 배열입니다.** 문자열·객체·배열 세 형태를 모두 받아 배열로 통일합니다
  (`normalize_yarn`). **문자열은 쉼표로 쪼개지 않습니다** — `"오메가 (186번 귤색)"`처럼
  이름 안에 쉼표가 있을 수 있어, 쪼개면 없던 실이 생깁니다.
  - **`gauge`는 영상에서 말한 경우에만 채웁니다.** 실측: 저장된 7건의 자막(총 13만 자)과
    설명란 전체에서 게이지 언급이 **0건**이었습니다. 없는 것이 정상입니다.
  - `source`가 `inferred`면 화면에 **(추정)** 이 붙습니다. 근거 없이 게이지만 있으면
    서버가 `inferred`로 낮춥니다.
  - **`spec.gauge_label`은 `gauge`와 다른 값입니다.** 실 라벨 기준이지 그 도안의 게이지가
    아닙니다. 메리노프린트는 라벨이 20코 × 27단인데 같은 실로 뜬 고양이귀 비니 도안은
    22코 × 31단입니다. 화면에서도 줄을 나눠 "실 라벨 기준"이라고 표시합니다.
- **`shop_links`의 네 갈래** — `pattern`(도안 판매) · `supply`(원작자 준비물) ·
  `channel`(채널 쇼핑몰) · `search`(우리가 만든 검색). **`search`는 나머지가 하나도
  없을 때만** 만들어지고, 화면에서도 "실 이름 링크"로만 나타납니다.
  창작자가 지정한 판매처와 우리 추측을 섞지 않기 위함입니다.
- **`formula` 표기 규칙** (Pass 2 프롬프트에 명시됨)
  - 약어와 숫자 사이 공백 1칸: `ch 1, sc 3, inc 1` (⭕) / `ch1, sc3` (❌)
  - 반복은 괄호 + `x 횟수`: `(sc 2, inc 1) x 4`
  - 구분자는 쉼표 + 공백
  - "(does not count as st)", "(코로 세지 않음)" 같은 부연설명 괄호는 금지 —
    서버의 `clean_pattern_text()`가 한 번 더 걸러냅니다
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
| 표에 없는 약어가 하나라도 있음 | `skipped` (`reason: unknown_term`) — **검증하지 않음** |
| 조립·마무리 단 (`total_stitches: 0`) 또는 코수 미기재 | 검증 대상 아님 (필드 없음) |
| 여러 단을 묶었는데 계산값이 적힌 코수의 **정확한 배수** | `skipped` (`reason: grouped_row`) |
| 사용자가 ⚠️를 눌러 확인함 | `acknowledged` — 경고로 세지 않음 |
| 계산값 == `total_stitches` 이고 소비도 정상 | 필드 없음 (통과) |
| 값이 다름 | `mismatch` + `reason` |

`reason`은 네 가지입니다.

| `reason` | 뜻 |
|---|---|
| `total_stitches` | 약어대로 세면 다른 수가 나옴 |
| `formula_uses` | 남는 코는 맞는데 **앞 단보다 많이 씀** |
| `formula_stitches` | 위 둘 다 어긋남 |
| `continuity` | 늘림·줄임이 없는데 앞 단과 코수가 달라짐 |

```json
"validation": { "status": "mismatch", "reason": "formula_stitches",
                "expected": 36, "parsed": 48, "uses": 36, "previous": 24 }
```

### 일부러 검사하지 않는 것

**경고가 틀리면 맞는 경고까지 무시당합니다.** 그래서 확실할 때만 경고합니다.

| 상황 | 왜 검사하지 않는가 |
|---|---|
| 앞 단의 코를 **적게** 쓰는 단 | 덮개·주머니·트임처럼 앞 단 일부에만 뜨는 편물이 정상적으로 존재합니다. **많이 쓰는 것은 여전히 잡습니다** — 앞 단에 없는 코를 뜰 수는 없으므로 확실한 오류입니다 |
| 여러 단을 한 줄로 묶었는데 코수가 정확한 배수 | `k 110, p 110` / 총 110코는 겉면·안면 **두 단**을 한 줄로 적은 것이지 한 단에서 220코를 뜬 것이 아닙니다 |

앞 항목은 연속성 검사에도 함께 적용합니다. 빼먹으면 같은 오탐이 `formula_uses` 대신
`continuity`로 옮겨와 똑같이 틀린 경고를 냅니다.

**효과**: 저장된 7건 기준 경고 11건 → 7건. 사라진 4건은 전부 오탐이었습니다.

### 추가 검사: 단 간 연속성

늘림·줄임이 없는 단인데 앞 단과 코수가 달라지면 의심 신호입니다.
`inc` / `dec` / **행 중간의 `ch`** 가 없는 단의 `total_stitches`가 직전 단과 다르면 `mismatch`(`reason: "continuity"`)로 표시합니다.

> ⚠️ **연쇄 오탐 방지**: 검증에 걸린 단의 코수는 다음 단의 비교 기준으로 쓰지 않습니다.
> 그렇게 하지 않으면 한 단이 틀렸을 때 뒤따르는 멀쩡한 단이 전부 경고로 뒤덮입니다.

### UI 처리

- 해당 행을 은은하게 강조하고 ⚠️ 배지 + 사유 툴팁. 상단에 "확인이 필요한 단 N개" 배너
- 도안 전체가 아니라 **문제가 된 단만** 표시 — 나머지 신뢰도를 깎지 않기 위함
- 사용자가 편집 모드로 직접 고칠 수 있고, ⚠️를 눌러 "확인함"으로 표시할 수도 있습니다.
  그때의 약어·코수를 `validation_ack`에 지문으로 남겨, 값이 바뀌면 확인이 자동으로 무효가 됩니다
- **자동 교정은 하지 않습니다.** AI가 계산을 두 번 틀릴 여지가 크기 때문입니다

---

## 5. 바늘 종류

`materials.needle.type`은 **`"코바늘"` 또는 `"대바늘"` 두 값만 허용**합니다.

- Pass 2 프롬프트에서 두 값 중 하나로 강제
- 서버에서 한 번 더 검증: 다른 값이면 `formula`에 등장하는 약어로 추론 (`sc`/`dc`/`mr` 계열 → 코바늘, `k`/`p` 계열 → 대바늘)
- 바늘 종류는 향후 **기법 사전 필터링**(코바늘 도안에 대바늘 기법이 섞이지 않게)과 **바늘 구매 링크 생성**에 쓰입니다

---

## 6. API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/generate` | 도안 생성. 같은 `video_id`가 있으면 DB 캐시를 즉시 반환 |
| `GET` | `/api/pattern/{id}` | 단건 조회 (+ 조회수 1 증가) |
| `PUT` | `/api/pattern/{id}` | 사용자가 고친 도안 저장 (⚠️ 인증 없음, `shop_links`는 서버 값 우선) |
| `GET` | `/api/patterns` | 목록. `?sort=recent\|popular&page=&size=&q=`. 본문은 빼고 카드용 정보만 |
| `GET` | `/api/craft-terms` | 용어사전. 한국 뜨개 기호표 순서로 정렬 + `group`/`group_label` |
| `POST` | `/api/reports` | 오류 신고 → `reports` |
| `GET` | `/api/health` | 모델·환경변수·호출량 소진 확인 |

### `/api/generate`의 처리 순서

돈이 나가는 지점과 검증 지점을 구분해 두는 것이 중요합니다.

```
video_id 추출 → DB 캐시 조회 ─(있으면 즉시 반환, 비용 0)
                    │ 없음
                    ▼
              호출량 한도 검사        ← 여기부터 비용 발생
                    ▼
              자막 수집 (Supadata)   ← 실패 시 원인별 안내 + 한도 환급
                    ▼
              Pass 1 → Pass 2 (Gemini 2회)
                    ▼
   sanitize → 바늘 정규화 → 실 정규화 → 실 사전 보완
        → 타임스탬프 보충(Pass 1) → 구매 링크 추출 → 채널 쇼핑몰 기억
        → 타임스탬프 검증 → 코수 검증
                    ▼
                 DB 저장
```
