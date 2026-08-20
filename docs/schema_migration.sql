-- ============================================================
-- Knotty 스키마 정비 (craft_terms 제외)
--
-- craft_terms는 docs/craft_terms_seed.sql 에서 따로 다룹니다.
-- 각 섹션은 독립적이므로 필요한 부분만 선택해서 실행해도 됩니다.
-- ============================================================


-- ------------------------------------------------------------
-- ① creators — 채널 정보 확장
-- ------------------------------------------------------------
-- 현재 구조는 channel_url 하나로 채널을 식별합니다.
-- 그런데 백엔드는 channelId를 못 읽으면 @핸들 주소로 fallback하므로,
-- 같은 채널이 두 형태로 저장될 수 있고 UNIQUE(channel_url)은 이를 막지 못합니다.
--   https://www.youtube.com/channel/UCyZYf...   ← 정상 경로
--   https://www.youtube.com/@sevy_handmade      ← fallback 경로
-- 그래서 불변 식별자인 channel_id를 따로 두고 중복을 한 번 더 막습니다.

alter table creators add column if not exists channel_id       text;   -- UC로 시작하는 불변 ID
alter table creators add column if not exists channel_handle   text;   -- @핸들 (표시용)
alter table creators add column if not exists thumbnail_url    text;   -- 채널 프로필 이미지

-- P2: 준비물 구매 링크 (POSITIONING.md 수익화 참고)
alter table creators add column if not exists shop_url         text;   -- 채널 운영 쇼핑몰 (실 구매)
alter table creators add column if not exists pattern_shop_url text;   -- 도안 판매처

-- P2: 창작자 opt-out — "내 영상은 빼주세요" 요청 처리용
alter table creators add column if not exists opt_out          boolean not null default false;

-- 같은 channel_id가 두 번 들어가지 않도록. NULL은 제약을 받지 않으므로
-- @핸들로만 저장된 기존 행이 있어도 문제되지 않습니다.
create unique index if not exists creators_channel_id_key on creators (channel_id);


-- ------------------------------------------------------------
-- ② patterns — 캐시 키와 게시판 준비
-- ------------------------------------------------------------
-- 캐시는 주소 원문이 아니라 video_id로 조회합니다.
-- 같은 영상이 &t=…, ?si=… 때문에 여러 건 저장되는 것을 막습니다.

-- 먼저 중복 확인 (결과가 있으면 아래 정리 후 인덱스 생성)
select video_id, count(*) from patterns group by video_id having count(*) > 1;

-- 중복이 있을 때만 실행: 가장 먼저 만들어진 1건만 남깁니다
-- delete from patterns p using patterns q
-- where p.video_id = q.video_id and p.created_at > q.created_at;

create unique index if not exists patterns_video_id_key on patterns (video_id);

-- P3: 게시판 · 인기 도안
alter table patterns add column if not exists view_count int not null default 0;

-- P2: 창작자 요청 시 숨김 처리
alter table patterns add column if not exists is_hidden boolean not null default false;

-- creator_id 참조 무결성 (이미 걸려 있으면 에러가 나므로 그때는 건너뛰세요)
-- alter table patterns add constraint patterns_creator_id_fkey
--   foreign key (creator_id) references creators(id) on delete set null;


-- ------------------------------------------------------------
-- ③ craft_terms_pending — 미등록 기법 큐
-- ------------------------------------------------------------
-- Pass 2가 기법 사전에 없는 기법을 만나면 여기에 쌓입니다.
-- 자주 등장하는 것부터 craft_terms로 승격시키면 됩니다.
-- 이 테이블이 없어도 도안 생성은 정상 동작하며, 기록만 건너뜁니다.

create table if not exists public.craft_terms_pending (
  id                uuid                     not null default gen_random_uuid(),
  raw_text          text                     not null,
  occurrence_count  int                      not null default 1,
  sample_pattern_id uuid                     null,
  status            text                     not null default 'pending',  -- pending | approved | rejected
  created_at        timestamp with time zone not null default now(),

  constraint craft_terms_pending_pkey primary key (id),
  constraint craft_terms_pending_raw_text_key unique (raw_text),
  constraint craft_terms_pending_sample_fkey
    foreign key (sample_pattern_id) references patterns(id) on delete set null
) TABLESPACE pg_default;


-- ------------------------------------------------------------
-- ④ reports — 오류 보고
-- ------------------------------------------------------------
-- "이 도안 이상해요" 버튼이 남기는 기록. 도안 수십 개 규모라 이걸로 충분합니다.

create table if not exists public.reports (
  id         uuid                     not null default gen_random_uuid(),
  pattern_id uuid                     null,
  step_ref   text                     null,   -- 문제가 된 파츠·단 (선택)
  message    text                     not null,
  created_at timestamp with time zone not null default now(),

  constraint reports_pkey primary key (id),
  constraint reports_pattern_fkey
    foreign key (pattern_id) references patterns(id) on delete cascade
) TABLESPACE pg_default;


-- ------------------------------------------------------------
-- ⑤ RLS — 노출된 publishable key 무력화
-- ------------------------------------------------------------
-- 백엔드는 secret key를 쓰므로 RLS를 우회합니다. 따라서 정책은 만들지 않습니다.
-- 브라우저는 Supabase에 직접 접근하지 않으므로 막아도 서비스에 영향이 없고,
-- publishable key가 유출돼 있어도 아무것도 읽히지 않습니다.

alter table patterns            enable row level security;
alter table creators            enable row level security;
alter table craft_terms         enable row level security;
alter table craft_terms_pending enable row level security;
alter table reports             enable row level security;


-- ------------------------------------------------------------
-- ⑥ 확인
-- ------------------------------------------------------------
select 'patterns' as t, count(*) from patterns
union all select 'creators', count(*) from creators
union all select 'craft_terms', count(*) from craft_terms
union all select 'craft_terms_pending', count(*) from craft_terms_pending
union all select 'reports', count(*) from reports;
