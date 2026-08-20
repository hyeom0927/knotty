-- ============================================================
-- Knotty 기법 사전 — 값 동기화 (UPDATE + 신규 추가)
--
-- craft_terms_seed.sql 의 내용을 기존 테이블에 반영합니다.
-- 테이블을 지우지 않으므로 직접 채워 넣으신 video_url 은 그대로 보존됩니다.
-- 몇 번을 실행해도 결과가 같습니다.
--
-- ⚠️ video_url 을 채우신 뒤에는 craft_terms_seed.sql 을 다시 실행하지 마세요.
--    그 파일은 맨 앞에서 테이블을 DROP 하므로 영상 링크가 전부 사라집니다.
-- ============================================================

insert into craft_terms
  (craft_type, entry_type, standard_code, kr_name, stitch_delta, description, thumbnail_url)
values
  ('crochet', 'stitch'::entry_type_enum, 'ch', '사슬뜨기', 1, '실을 걸어 빼내며 사슬을 만드는 가장 기본 기법. 기초 사슬과 기둥사슬에 쓰입니다.', 'symbols/ch.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'sl_st', '빼뜨기', 0, '코에 바늘을 넣어 실을 그대로 빼내는 기법. 원형 연결·이동에 쓰이며 보통 코수에 넣지 않습니다. 도안에는 sl st로 표기합니다.', 'symbols/sl_st.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'sc', '짧은뜨기', 1, '가장 기본이 되는 촘촘한 기법. 인형·소품에 널리 쓰입니다. 영국식 도안에서는 dc로 표기하므로 미국식 dc(한길긴뜨기)와 혼동하지 마세요.', 'symbols/sc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'hdc', '긴뜨기', 1, '실을 한 번 걸고 세 고리를 한 번에 빼내는 기법. 짧은뜨기와 한길긴뜨기의 중간 높이입니다. 영국식은 htr입니다.', 'symbols/hdc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'dc', '한길긴뜨기', 1, '실을 한 번 걸고 두 번에 나눠 빼내는 기법. 무늬뜨기에 가장 많이 쓰입니다. 영국식 도안에서는 tr로 표기하므로 미국식 tr(두길긴뜨기)와 혼동하지 마세요.', 'symbols/dc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'tr', '두길긴뜨기', 1, '실을 두 번 걸어 뜨는 기법. 한길긴뜨기보다 기둥이 높습니다. 도안 기호는 T에 빗금 2개입니다. 영국식은 dtr입니다.', 'symbols/tr.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'dtr', '세길긴뜨기', 1, '실을 세 번 걸어 뜨는 기법. 레이스나 성긴 무늬에 쓰입니다. 도안 기호는 T에 빗금 3개입니다. 영국식은 trtr입니다.', 'symbols/dtr.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'mr', '매직링', 0, '실로 조절 가능한 고리를 만들어 원형 뜨기를 시작하는 방법. 사슬 원형코와 달리 중앙 구멍을 조여 막을 수 있습니다. 도안에는 MR로도 표기합니다.', 'symbols/mr.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'inc', '짧은뜨기 2코 늘려뜨기', 2, '한 코에 짧은뜨기를 2개 떠서 1코를 늘립니다. 도안에는 2 sc in next st로도 표기합니다.', 'symbols/inc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'dec', '짧은뜨기 2코 모아뜨기', 1, '짧은뜨기 2개를 한 번에 마무리해 1코로 줄입니다. 도안에는 sc2tog로도 표기합니다.', 'symbols/dec.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'sc3tog', '짧은뜨기 3코 모아뜨기', 1, '짧은뜨기 3개를 한 번에 마무리해 2코를 줄입니다.', 'symbols/sc3tog.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'dc2inc', '한길긴뜨기 2코 늘려뜨기', 2, '한 코에 한길긴뜨기를 2개 떠서 1코를 늘립니다. 도안에는 dc inc 또는 2 dc in next st로 표기합니다.', 'symbols/dc2inc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'sc3inc', '짧은뜨기 3코 늘려뜨기', 3, '한 코에 짧은뜨기를 3개 떠서 2코를 늘립니다. 도안에는 sc 3 in 1 st 또는 3 sc in next st로도 표기합니다.', 'symbols/sc3inc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'hdc2inc', '긴뜨기 2코 늘려뜨기', 2, '한 코에 긴뜨기를 2개 떠서 1코를 늘립니다. 도안에는 hdc inc 또는 2 hdc in next st로 표기합니다.', 'symbols/hdc2inc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'tr3inc', '두길긴뜨기 3코 늘려뜨기', 3, '한 코에 두길긴뜨기를 3개 떠서 2코를 늘립니다. 도안에는 tr inc3 또는 3 tr in next st로 표기합니다.', 'symbols/tr3inc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'dc2tog', '한길긴뜨기 2코 모아뜨기', 1, '한길긴뜨기 2개를 한 번에 마무리해 1코로 줄입니다.', 'symbols/dc2tog.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'dc3tog', '한길긴뜨기 3코 모아뜨기', 1, '한길긴뜨기 3개를 한 번에 마무리해 2코를 줄입니다.', 'symbols/dc3tog.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'dc4tog', '한길긴뜨기 4코 모아뜨기', 1, '한길긴뜨기 4개를 한 번에 마무리해 3코를 줄입니다.', 'symbols/dc4tog.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'puff', '긴뜨기 5코 퍼프뜨기', 1, '한 코에 긴뜨기를 5번 걸어 한 번에 빼내는 도톰한 기법. 퍼프 스티치. 구슬뜨기·팝콘뜨기와 달리 코를 완성하지 않고 걸어둔 실을 한 번에 빼냅니다. 도안에는 puff st 또는 hdc5tog로 표기합니다.', 'symbols/puff.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'bobble', '한길긴뜨기 5코 구슬뜨기', 1, '한 코에 한길긴뜨기 5개를 모아떠 구슬처럼 볼록하게 만듭니다. 버블 스티치. 팝콘뜨기와 달리 마지막에 한 번에 빼내 봉긋하게 솟습니다. 도안에는 bobble 또는 dc5tog로 표기합니다.', 'symbols/bobble.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'popcorn', '한길긴뜨기 5코 팝콘뜨기', 1, '한 코에 한길긴뜨기 5개를 뜬 뒤 첫 코로 빼내어 팝콘처럼 튀어나오게 합니다. 구슬뜨기와 달리 각 코를 완성한 뒤 앞으로 밀어냅니다. 도안에는 popcorn을 줄여 pc로 표기합니다.', 'symbols/popcorn.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'fpdc', '앞걸어 한길긴뜨기', 1, '앞단 기둥을 앞쪽에서 감아 뜨는 한길긴뜨기. 골지 무늬에 씁니다. 도안에는 FPdc로 표기합니다.', 'symbols/fpdc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'bpdc', '뒤걸어 한길긴뜨기', 1, '앞단 기둥을 뒤쪽에서 감아 뜨는 한길긴뜨기. 골지 무늬에 씁니다. 도안에는 BPdc로 표기합니다.', 'symbols/bpdc.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'flo', '앞이랑뜨기', 0, '코의 앞쪽 반 코에만 바늘을 넣어 뜹니다. 코수는 변하지 않습니다. 도안에는 FLO로 표기합니다.', 'symbols/flo.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'blo', '뒤이랑뜨기', 0, '코의 뒤쪽 반 코에만 바늘을 넣어 뜹니다. 코수는 변하지 않습니다. 도안에는 BLO로 표기합니다.', 'symbols/blo.svg'),
  ('crochet', 'stitch'::entry_type_enum, 'crab', '새우뜨기', 1, '진행 방향을 거꾸로 뜨는 짧은뜨기. 테두리를 단단히 마무리할 때 씁니다. 역짧은뜨기. 도안에는 rev sc 또는 crab st로 표기합니다.', 'symbols/crab.svg'),
  ('crochet', 'technique'::entry_type_enum, 'color_change', '배색', null, '실 색을 바꾸는 방법. 직전 코의 마지막 실을 빼낼 때 새 실로 바꾸면 경계가 깔끔합니다.', null),
  ('crochet', 'technique'::entry_type_enum, 'oval_base', '타원형 만들기', null, '기초 사슬의 양옆을 둘러 뜨며 타원형 밑판을 만드는 방법입니다.', null),
  ('crochet', 'technique'::entry_type_enum, 'ring_base', '사슬 원형코 만들기', null, '사슬을 이어 고리를 만들고 그 안에 떠 넣는 원형 시작 방법. 매직링(mr)과 달리 중앙에 구멍이 남습니다.', null),
  ('crochet', 'technique'::entry_type_enum, 'sew_finish', '돗바늘 마무리', null, '돗바늘로 실 끝을 편물 안에 감추거나 편물끼리 잇는 마무리 과정입니다.', null),
  ('knitting', 'stitch'::entry_type_enum, 'k', '겉뜨기', 1, '가장 기본이 되는 대바늘 기법. 겉면이 브이(V) 모양으로 보입니다.', 'symbols/k.svg'),
  ('knitting', 'stitch'::entry_type_enum, 'p', '안뜨기', 1, '겉뜨기의 반대 방향으로 뜨는 기법. 겉면이 가로줄 모양으로 보입니다.', 'symbols/p.svg'),
  ('knitting', 'stitch'::entry_type_enum, 'yo', '바늘비우기', 1, '실을 바늘에 걸어 구멍과 함께 1코를 늘립니다. 레이스 무늬의 기본입니다.', 'symbols/yo.svg'),
  ('knitting', 'stitch'::entry_type_enum, 'k2tog', '오른코 겹쳐 2코 모아뜨기', 1, '2코를 함께 겉뜨기해 1코로 줄입니다. 오른쪽으로 기웁니다. 왼쪽으로 기우는 ssk(왼코 겹쳐 2코 모아뜨기)와 짝을 이룹니다.', 'symbols/k2tog.svg'),
  ('knitting', 'stitch'::entry_type_enum, 'ssk', '왼코 겹쳐 2코 모아뜨기', 1, '2코를 겉뜨기 방향으로 옮긴 뒤 함께 떠 1코로 줄입니다. 왼쪽으로 기웁니다. 오른쪽으로 기우는 k2tog(오른코 겹쳐 2코 모아뜨기)와 짝을 이룹니다.', 'symbols/ssk.svg'),
  ('knitting', 'stitch'::entry_type_enum, 'co', '코잡기', 1, '대바늘 뜨기를 시작할 때 첫 단의 코를 만드는 과정입니다. 도안에는 CO로 표기합니다.', 'symbols/co.svg')

on conflict (craft_type, standard_code) do update set
  entry_type    = excluded.entry_type,
  kr_name       = excluded.kr_name,
  stitch_delta  = excluded.stitch_delta,
  description   = excluded.description,
  thumbnail_url = excluded.thumbnail_url;
  -- video_url 은 일부러 갱신하지 않습니다


-- ------------------------------------------------------------
-- 확인
-- ------------------------------------------------------------
select craft_type, entry_type, count(*) from craft_terms
group by craft_type, entry_type order by 1,2;
-- 기대: crochet/stitch 26, crochet/technique 4, knitting/stitch 6  (총 36)

-- formula에 등장하는 코드에 언더스코어가 남았는지 (sl_st 만 정상)
select standard_code from craft_terms
where entry_type = 'stitch' and standard_code like '%\_%';
-- 기대: sl_st 1건
