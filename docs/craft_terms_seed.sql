-- ============================================================
-- Knotty 기법 사전 (craft_terms) — 테이블 생성 + 시드
--
-- ⚠️ 기존 craft_terms를 지우고 새로 만듭니다.
--    지금 들어 있는 값은 전부 이 스크립트가 넣은 시드라 잃을 것이 없습니다.
--    ①의 drop 주석을 풀고 전체를 한 번에 실행하세요.
--
-- 구성: 코바늘 약어 22 + 코바늘 용어 4 + 대바늘 약어 6 = 총 32건
-- ============================================================


-- ------------------------------------------------------------
-- 컬럼 사용 규칙
-- ------------------------------------------------------------
-- standard_code : Knotty의 유일한 기법 식별자.
--                 formula에 등장하고, Pass 2 프롬프트에 주입되며,
--                 코수 검증기가 매칭하는 키. 소문자 + 언더스코어.
--                 미국식 약어를 기본으로 하되, 약어가 모호하거나 여러 형태로
--                 통용되는 기법(puff, bobble, popcorn, crab)은 알아보기 쉬운 이름을 씁니다.
--                 실제 도안에서 쓰이는 다른 표기는 description에 적습니다.
--
-- entry_type    : 'stitch'    → formula에 등장. 프롬프트 주입 + 코수 검증 대상
--                 'technique' → 용어사전에만 표시. 프롬프트에 주입되지 않음
--
-- stitch_delta  : 이 기법 1개가 편물에 남기는 코의 수 (코수 검증용)
--
-- thumbnail_url : 도안 기호 이미지 경로. symbols/ 폴더의 SVG를 가리킵니다.
--                 ⑤에서 standard_code로부터 자동 생성되므로 직접 적지 않습니다.
--                 (유니코드 글자로는 "T에 빗금 2개/3개"를 표현할 수 없어 이미지로 갑니다)
--
-- video_url     : 기법 설명 영상. 지금은 비워둡니다. ⑥에서 나중에 채웁니다.


-- ------------------------------------------------------------
-- ① 타입 · 테이블 생성
-- ------------------------------------------------------------
-- drop table if exists public.craft_terms cascade;
-- drop type  if exists craft_type_enum;
-- drop type  if exists entry_type_enum;

-- enum으로 두면 정해진 값만 들어가고, Supabase 테이블 편집기에서 드롭다운으로 고를 수 있습니다.
-- (varchar였을 때는 'crochet' 오타나 엉뚱한 값도 그대로 저장됐습니다)
create type craft_type_enum as enum ('crochet', 'knitting');
create type entry_type_enum as enum ('stitch', 'technique');

create table public.craft_terms (
  id            uuid                     not null default gen_random_uuid(),
  -- 기본값을 두지 않아 새 행을 넣을 때 코바늘/대바늘을 반드시 고르게 합니다
  craft_type    craft_type_enum          not null,
  standard_code character varying(50)    not null,
  kr_name       character varying(100)   not null,
  description   text                     null,
  video_url     text                     null,
  thumbnail_url text                     null,
  created_at    timestamp with time zone null default now(),
  entry_type    entry_type_enum          not null default 'stitch',
  stitch_delta  integer                  null,

  constraint craft_terms_pkey primary key (id),
  constraint unique_craft_code unique (craft_type, standard_code)
) TABLESPACE pg_default;


-- ------------------------------------------------------------
-- ② 코바늘 — 도안 약어 (22건)
-- ------------------------------------------------------------
insert into craft_terms
  (craft_type, entry_type, standard_code, kr_name, stitch_delta, description)
values
  -- 기본 기법 ---------------------------------------------------
  ('crochet','stitch','ch',    '사슬뜨기',    1,
   '실을 걸어 빼내며 사슬을 만드는 가장 기본 기법. 기초 사슬과 기둥사슬에 쓰입니다.'),
  ('crochet','stitch','sl_st', '빼뜨기',      0,
   '코에 바늘을 넣어 실을 그대로 빼내는 기법. 원형 연결·이동에 쓰이며 보통 코수에 넣지 않습니다. 도안에는 sl st로 표기합니다.'),
  ('crochet','stitch','sc',    '짧은뜨기',    1,
   '가장 기본이 되는 촘촘한 기법. 인형·소품에 널리 쓰입니다. 영국식 도안에서는 dc로 표기하므로 미국식 dc(한길긴뜨기)와 혼동하지 마세요.'),
  ('crochet','stitch','hdc',   '긴뜨기',      1,
   '실을 한 번 걸고 세 고리를 한 번에 빼내는 기법. 짧은뜨기와 한길긴뜨기의 중간 높이입니다. 영국식은 htr입니다.'),
  ('crochet','stitch','dc',    '한길긴뜨기',  1,
   '실을 한 번 걸고 두 번에 나눠 빼내는 기법. 무늬뜨기에 가장 많이 쓰입니다. 영국식 도안에서는 tr로 표기하므로 미국식 tr(두길긴뜨기)와 혼동하지 마세요.'),
  ('crochet','stitch','tr',    '두길긴뜨기',  1,
   '실을 두 번 걸어 뜨는 기법. 한길긴뜨기보다 기둥이 높습니다. 도안 기호는 T에 빗금 2개입니다. 영국식은 dtr입니다.'),
  ('crochet','stitch','dtr',   '세길긴뜨기',  1,
   '실을 세 번 걸어 뜨는 기법. 레이스나 성긴 무늬에 쓰입니다. 도안 기호는 T에 빗금 3개입니다. 영국식은 trtr입니다.'),
  ('crochet','stitch','mr',    '매직링',      0,
   '실로 조절 가능한 고리를 만들어 원형 뜨기를 시작하는 방법. 사슬 원형코와 달리 중앙 구멍을 조여 막을 수 있습니다. 도안에는 MR로도 표기합니다.'),

  -- 늘림 · 줄임 -------------------------------------------------
  ('crochet','stitch','inc',    '짧은뜨기 2코 늘려뜨기',    2,
   '한 코에 짧은뜨기를 2개 떠서 1코를 늘립니다. 도안에는 2 sc in next st로도 표기합니다.'),
  ('crochet','stitch','dec',    '짧은뜨기 2코 모아뜨기',    1,
   '짧은뜨기 2개를 한 번에 마무리해 1코로 줄입니다. 도안에는 sc2tog로도 표기합니다.'),
  ('crochet','stitch','sc3tog', '짧은뜨기 3코 모아뜨기',    1,
   '짧은뜨기 3개를 한 번에 마무리해 2코를 줄입니다.'),
  ('crochet','stitch','dc_inc', '한길긴뜨기 2코 늘려뜨기',  2,
   '한 코에 한길긴뜨기를 2개 떠서 1코를 늘립니다. 도안에는 dc inc 또는 2 dc in next st로 표기합니다.'),
  ('crochet','stitch','dc2tog', '한길긴뜨기 2코 모아뜨기',  1,
   '한길긴뜨기 2개를 한 번에 마무리해 1코로 줄입니다.'),
  ('crochet','stitch','dc3tog', '한길긴뜨기 3코 모아뜨기',  1,
   '한길긴뜨기 3개를 한 번에 마무리해 2코를 줄입니다.'),

  -- 입체 무늬 ---------------------------------------------------
  ('crochet','stitch','puff',    '긴뜨기 5코 퍼프뜨기',      1,
   '한 코에 긴뜨기를 5번 걸어 한 번에 빼내는 도톰한 기법. 퍼프 스티치. 구슬뜨기·팝콘뜨기와 달리 코를 완성하지 않고 걸어둔 실을 한 번에 빼냅니다. 도안에는 puff st 또는 hdc5tog로 표기합니다.'),
  ('crochet','stitch','bobble',  '한길긴뜨기 5코 구슬뜨기',  1,
   '한 코에 한길긴뜨기 5개를 모아떠 구슬처럼 볼록하게 만듭니다. 버블 스티치. 팝콘뜨기와 달리 마지막에 한 번에 빼내 봉긋하게 솟습니다. 도안에는 bobble 또는 dc5tog로 표기합니다.'),
  ('crochet','stitch','popcorn', '한길긴뜨기 5코 팝콘뜨기',  1,
   '한 코에 한길긴뜨기 5개를 뜬 뒤 첫 코로 빼내어 팝콘처럼 튀어나오게 합니다. 구슬뜨기와 달리 각 코를 완성한 뒤 앞으로 밀어냅니다. 도안에는 popcorn을 줄여 pc로 표기합니다.'),

  -- 걸어뜨기 ----------------------------------------------------
  ('crochet','stitch','fpdc', '앞걸어 한길긴뜨기',  1,
   '앞단 기둥을 앞쪽에서 감아 뜨는 한길긴뜨기. 골지 무늬에 씁니다. 도안에는 FPdc로 표기합니다.'),
  ('crochet','stitch','bpdc', '뒤걸어 한길긴뜨기',  1,
   '앞단 기둥을 뒤쪽에서 감아 뜨는 한길긴뜨기. 골지 무늬에 씁니다. 도안에는 BPdc로 표기합니다.'),

  -- 뜨는 위치 지정 (코수를 늘리지 않음) --------------------------
  ('crochet','stitch','flo', '앞이랑뜨기',  0,
   '코의 앞쪽 반 코에만 바늘을 넣어 뜹니다. 코수는 변하지 않습니다. 도안에는 FLO로 표기합니다.'),
  ('crochet','stitch','blo', '뒤이랑뜨기',  0,
   '코의 뒤쪽 반 코에만 바늘을 넣어 뜹니다. 코수는 변하지 않습니다. 도안에는 BLO로 표기합니다.'),

  -- 마무리 ------------------------------------------------------
  ('crochet','stitch','crab', '새우뜨기',  1,
   '진행 방향을 거꾸로 뜨는 짧은뜨기. 테두리를 단단히 마무리할 때 씁니다. 역짧은뜨기. 도안에는 rev sc 또는 crab st로 표기합니다.');


-- ------------------------------------------------------------
-- ③ 코바늘 — 용어사전 전용 (4건)
-- ------------------------------------------------------------
-- 약어도 코수도 없는 "과정"입니다. stitch_delta가 비어 있는 것이 정상입니다.
-- entry_type='technique' 이므로 AI 프롬프트에 주입되지 않습니다.
-- (주입되면 AI가 formula에 color_change 같은 값을 적어 도안 약어가 오염됩니다)

insert into craft_terms
  (craft_type, entry_type, standard_code, kr_name, stitch_delta, description)
values
  ('crochet','technique','color_change', '배색',          null,
   '실 색을 바꾸는 방법. 직전 코의 마지막 실을 빼낼 때 새 실로 바꾸면 경계가 깔끔합니다.'),
  ('crochet','technique','oval_base',    '타원형 만들기',  null,
   '기초 사슬의 양옆을 둘러 뜨며 타원형 밑판을 만드는 방법입니다.'),
  ('crochet','technique','ring_base',    '사슬 원형코 만들기',  null,
   '사슬을 이어 고리를 만들고 그 안에 떠 넣는 원형 시작 방법. 매직링(mr)과 달리 중앙에 구멍이 남습니다.'),
  ('crochet','technique','sew_finish',   '돗바늘 마무리',  null,
   '돗바늘로 실 끝을 편물 안에 감추거나 편물끼리 잇는 마무리 과정입니다.');


-- ------------------------------------------------------------
-- ④ 대바늘 — 도안 약어 (6건)
-- ------------------------------------------------------------
insert into craft_terms
  (craft_type, entry_type, standard_code, kr_name, stitch_delta, description)
values
  ('knitting','stitch','k',     '겉뜨기',                  1,
   '가장 기본이 되는 대바늘 기법. 겉면이 브이(V) 모양으로 보입니다.'),
  ('knitting','stitch','p',     '안뜨기',                  1,
   '겉뜨기의 반대 방향으로 뜨는 기법. 겉면이 가로줄 모양으로 보입니다.'),
  ('knitting','stitch','yo',    '바늘비우기',              1,
   '실을 바늘에 걸어 구멍과 함께 1코를 늘립니다. 레이스 무늬의 기본입니다.'),
  ('knitting','stitch','k2tog', '오른코 겹쳐 2코 모아뜨기', 1,
   '2코를 함께 겉뜨기해 1코로 줄입니다. 오른쪽으로 기웁니다. 왼쪽으로 기우는 ssk(왼코 겹쳐 2코 모아뜨기)와 짝을 이룹니다.'),
  ('knitting','stitch','ssk',   '왼코 겹쳐 2코 모아뜨기',  1,
   '2코를 겉뜨기 방향으로 옮긴 뒤 함께 떠 1코로 줄입니다. 왼쪽으로 기웁니다. 오른쪽으로 기우는 k2tog(오른코 겹쳐 2코 모아뜨기)와 짝을 이룹니다.'),
  ('knitting','stitch','co',    '코잡기',                  1,
   '대바늘 뜨기를 시작할 때 첫 단의 코를 만드는 과정입니다. 도안에는 CO로 표기합니다.');


-- ------------------------------------------------------------
-- ⑤ 도안 기호 이미지 연결
-- ------------------------------------------------------------
-- symbols/ 폴더의 SVG 파일명이 standard_code와 같으므로 한 줄로 전부 채워집니다.
-- 나중에 기법을 추가해도 이 문장만 다시 돌리면 됩니다.
-- 그리기 규칙은 docs/SYMBOLS.md 참고.

update craft_terms
set thumbnail_url = 'symbols/' || standard_code || '.svg'
where entry_type = 'stitch';


-- ------------------------------------------------------------
-- ⑥ 확인
-- ------------------------------------------------------------
select craft_type, entry_type, count(*)
from craft_terms group by craft_type, entry_type order by 1, 2;
-- 기대: crochet/stitch 22, crochet/technique 4, knitting/stitch 6  (총 32)

-- 코수가 비어 있는 stitch 항목이 있으면 그 기법이 든 단은 검증에서 제외됩니다
select standard_code, kr_name from craft_terms
where entry_type = 'stitch' and stitch_delta is null;
-- 기대: 0건

-- 기호 이미지가 연결된 항목
select standard_code, kr_name, thumbnail_url from craft_terms
where thumbnail_url is not null order by craft_type, standard_code;
-- 기대: 28건 (stitch 전부. technique 4건은 기호가 없는 것이 정상)


-- ------------------------------------------------------------
-- ⑥ 기법 영상 링크 채우기 (나중에 별도 실행)
-- ------------------------------------------------------------
-- craft_type을 함께 지정해야 대바늘·코바늘의 같은 약어가 섞이지 않습니다.
--
-- update craft_terms set video_url = 'https://www.youtube.com/watch?v=...'
--   where craft_type = 'crochet' and standard_code = 'ch';

-- 아직 영상이 없는 항목
-- select craft_type, standard_code, kr_name from craft_terms
-- where video_url is null order by craft_type, entry_type, standard_code;
