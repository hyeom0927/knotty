-- ============================================================
-- Knotty 실 사전 (yarn_specs) — 테이블 생성 + 시드
--
-- 영상에는 게이지가 거의 나오지 않습니다. 저장된 도안 7건의 자막(총 13만 자)과
-- 설명란을 전수 검사한 결과 **게이지 언급이 0건**이었습니다.
-- 그래서 실 이름으로 사전을 찾아 보완합니다.
--
-- ⚠️ 이 표는 **실 라벨 기준 정보**입니다. 그 도안의 게이지가 아닙니다.
--    실제로 메리노프린트는 라벨 게이지가 20코 × 27단인데,
--    같은 실로 뜬 「고양이귀 비니」 도안의 게이지는 22코 × 31단입니다.
--    화면에서도 반드시 "실 라벨 기준"이라고 구분해 보여줘야 합니다.
--
-- 실행하지 않아도 서비스는 정상 동작하며, 이 기능만 조용히 꺼집니다.
-- (craft_terms_pending과 같은 방식)
-- ============================================================

create table if not exists yarn_specs (
  id           uuid primary key default gen_random_uuid(),
  name         text not null,          -- 대표 이름 (예: 메리노프린트)
  aliases      text[] default '{}',    -- 자막에서 달리 불리는 이름 (예: {메리노 프린트})
  brand        text,                   -- 판매처 (예: 바늘이야기)
  craft_type   text,                   -- crochet / knit / both
  weight_class text,                   -- 굵기 등급 (예: 중세사, 합태, 극세사)
  needle_size  text,                   -- 권장 바늘 호수 (예: 4/0~5/0호)
  ball_weight  text,                   -- 1볼 중량 (예: 30g±3g)
  ball_length  text,                   -- 1볼 길이 (예: 60m±5m)
  gauge_label  text,                   -- 라벨 기준 게이지. 코바늘 실은 대개 없음 → null
  source_url   text,                   -- 이 값을 확인한 페이지. 나중에 검증할 수 있게 남깁니다
  created_at   timestamptz default now()
);

-- 이름으로 찾는 표이므로 이름에 인덱스를 겁니다
create unique index if not exists yarn_specs_name_key on yarn_specs (lower(name));


-- ------------------------------------------------------------
-- 시드 (2026-08-23 확인)
-- ------------------------------------------------------------
-- 값을 채울 때 지키는 규칙:
--   1. **확인한 페이지가 있는 값만 넣습니다.** 모르면 null로 둡니다.
--      틀린 게이지는 사용자가 완성 크기를 통째로 잘못 잡게 만듭니다.
--   2. 코바늘 실은 게이지가 없는 것이 정상입니다. 억지로 채우지 마세요.
--      대신 `needle_size`와 `ball_weight`/`ball_length`가 대체 실을 고르는 데 쓰입니다.
--   3. `source_url`을 반드시 남깁니다. 나중에 이 값이 맞는지 되짚을 수 있어야 합니다.

insert into yarn_specs (name, aliases, brand, craft_type, weight_class, needle_size, ball_weight, ball_length, gauge_label, source_url)
values
  ('메리노프린트', '{메리노 프린트, Merino Print}', '바늘이야기', 'knit',
   NULL, NULL, '100g', NULL, '10x10cm = 20코 × 27단',
   'https://www.banul.co.kr/shop/shopdetail.html?branduid=10612645'),

  ('롤리코튼', '{롤리 코튼}', '앵콜스', 'crochet',
   NULL, '4/0~5/0호', '30g±3g', '60m±5m', NULL,
   'https://m.ancalls.com/product/detail.html?product_no=5398')

on conflict (lower(name)) do update set
  aliases      = excluded.aliases,
  brand        = excluded.brand,
  craft_type   = excluded.craft_type,
  weight_class = excluded.weight_class,
  needle_size  = excluded.needle_size,
  ball_weight  = excluded.ball_weight,
  ball_length  = excluded.ball_length,
  gauge_label  = excluded.gauge_label,
  source_url   = excluded.source_url;


-- ------------------------------------------------------------
-- 새 실을 추가할 때
-- ------------------------------------------------------------
-- 자주 등장하는데 사전에 없는 실은 로그에 남습니다:
--   🧵 사전에 없는 실: 퍼지퍼지 실, 신놀리 코튼
-- 그 이름으로 판매처 상세 페이지를 열어 확인한 값만 아래처럼 추가하세요.
--
-- insert into yarn_specs (name, brand, craft_type, needle_size, ball_weight, source_url)
-- values ('퍼지퍼지', '앵콜스', 'crochet', NULL, NULL, 'https://…');
