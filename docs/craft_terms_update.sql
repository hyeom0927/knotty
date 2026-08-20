-- ============================================================
-- Knotty 기법 사전 — 값 동기화 (UPDATE 전용)
--
-- craft_terms_seed.sql 의 내용을 기존 테이블에 덮어씁니다.
-- 테이블을 지우지 않으므로 직접 채워 넣으신 video_url 은 그대로 보존됩니다.
-- 몇 번을 실행해도 결과가 같습니다.
--
-- ⚠️ video_url 을 채우신 뒤에는 craft_terms_seed.sql 을 다시 실행하지 마세요.
--    그 파일은 맨 앞에서 테이블을 DROP 하므로 영상 링크가 전부 사라집니다.
--    앞으로 사전 내용을 고칠 때는 이 파일을 쓰세요.
-- ============================================================

update craft_terms t set
  kr_name       = v.kr_name,
  description   = v.description,
  entry_type    = v.entry_type::entry_type_enum,
  stitch_delta  = v.stitch_delta,
  thumbnail_url = case when v.entry_type = 'stitch'
                       then 'symbols/' || t.standard_code || '.svg'
                       else t.thumbnail_url end
from (values
  ('crochet', 'ch', '사슬뜨기', 'stitch', 1, '실을 걸어 빼내며 사슬을 만드는 가장 기본 기법. 기초 사슬과 기둥사슬에 쓰입니다.'),
  ('crochet', 'sl_st', '빼뜨기', 'stitch', 0, '코에 바늘을 넣어 실을 그대로 빼내는 기법. 원형 연결·이동에 쓰이며 보통 코수에 넣지 않습니다. 도안에는 sl st로 표기합니다.'),
  ('crochet', 'sc', '짧은뜨기', 'stitch', 1, '가장 기본이 되는 촘촘한 기법. 인형·소품에 널리 쓰입니다. 영국식 도안에서는 dc로 표기하므로 미국식 dc(한길긴뜨기)와 혼동하지 마세요.'),
  ('crochet', 'hdc', '긴뜨기', 'stitch', 1, '실을 한 번 걸고 세 고리를 한 번에 빼내는 기법. 짧은뜨기와 한길긴뜨기의 중간 높이입니다. 영국식은 htr입니다.'),
  ('crochet', 'dc', '한길긴뜨기', 'stitch', 1, '실을 한 번 걸고 두 번에 나눠 빼내는 기법. 무늬뜨기에 가장 많이 쓰입니다. 영국식 도안에서는 tr로 표기하므로 미국식 tr(두길긴뜨기)와 혼동하지 마세요.'),
  ('crochet', 'tr', '두길긴뜨기', 'stitch', 1, '실을 두 번 걸어 뜨는 기법. 한길긴뜨기보다 기둥이 높습니다. 도안 기호는 T에 빗금 2개입니다. 영국식은 dtr입니다.'),
  ('crochet', 'dtr', '세길긴뜨기', 'stitch', 1, '실을 세 번 걸어 뜨는 기법. 레이스나 성긴 무늬에 쓰입니다. 도안 기호는 T에 빗금 3개입니다. 영국식은 trtr입니다.'),
  ('crochet', 'mr', '매직링', 'stitch', 0, '실로 조절 가능한 고리를 만들어 원형 뜨기를 시작하는 방법. 사슬 원형코와 달리 중앙 구멍을 조여 막을 수 있습니다. 도안에는 MR로도 표기합니다.'),
  ('crochet', 'inc', '짧은뜨기 2코 늘려뜨기', 'stitch', 2, '한 코에 짧은뜨기를 2개 떠서 1코를 늘립니다. 도안에는 2 sc in next st로도 표기합니다.'),
  ('crochet', 'dec', '짧은뜨기 2코 모아뜨기', 'stitch', 1, '짧은뜨기 2개를 한 번에 마무리해 1코로 줄입니다. 도안에는 sc2tog로도 표기합니다.'),
  ('crochet', 'sc3tog', '짧은뜨기 3코 모아뜨기', 'stitch', 1, '짧은뜨기 3개를 한 번에 마무리해 2코를 줄입니다.'),
  ('crochet', 'dc_inc', '한길긴뜨기 2코 늘려뜨기', 'stitch', 2, '한 코에 한길긴뜨기를 2개 떠서 1코를 늘립니다. 도안에는 dc inc 또는 2 dc in next st로 표기합니다.'),
  ('crochet', 'dc2tog', '한길긴뜨기 2코 모아뜨기', 'stitch', 1, '한길긴뜨기 2개를 한 번에 마무리해 1코로 줄입니다.'),
  ('crochet', 'dc3tog', '한길긴뜨기 3코 모아뜨기', 'stitch', 1, '한길긴뜨기 3개를 한 번에 마무리해 2코를 줄입니다.'),
  ('crochet', 'puff', '긴뜨기 5코 퍼프뜨기', 'stitch', 1, '한 코에 긴뜨기를 5번 걸어 한 번에 빼내는 도톰한 기법. 퍼프 스티치. 구슬뜨기·팝콘뜨기와 달리 코를 완성하지 않고 걸어둔 실을 한 번에 빼냅니다. 도안에는 puff st 또는 hdc5tog로 표기합니다.'),
  ('crochet', 'bobble', '한길긴뜨기 5코 구슬뜨기', 'stitch', 1, '한 코에 한길긴뜨기 5개를 모아떠 구슬처럼 볼록하게 만듭니다. 버블 스티치. 팝콘뜨기와 달리 마지막에 한 번에 빼내 봉긋하게 솟습니다. 도안에는 bobble 또는 dc5tog로 표기합니다.'),
  ('crochet', 'popcorn', '한길긴뜨기 5코 팝콘뜨기', 'stitch', 1, '한 코에 한길긴뜨기 5개를 뜬 뒤 첫 코로 빼내어 팝콘처럼 튀어나오게 합니다. 구슬뜨기와 달리 각 코를 완성한 뒤 앞으로 밀어냅니다. 도안에는 popcorn을 줄여 pc로 표기합니다.'),
  ('crochet', 'fpdc', '앞걸어 한길긴뜨기', 'stitch', 1, '앞단 기둥을 앞쪽에서 감아 뜨는 한길긴뜨기. 골지 무늬에 씁니다. 도안에는 FPdc로 표기합니다.'),
  ('crochet', 'bpdc', '뒤걸어 한길긴뜨기', 'stitch', 1, '앞단 기둥을 뒤쪽에서 감아 뜨는 한길긴뜨기. 골지 무늬에 씁니다. 도안에는 BPdc로 표기합니다.'),
  ('crochet', 'flo', '앞이랑뜨기', 'stitch', 0, '코의 앞쪽 반 코에만 바늘을 넣어 뜹니다. 코수는 변하지 않습니다. 도안에는 FLO로 표기합니다.'),
  ('crochet', 'blo', '뒤이랑뜨기', 'stitch', 0, '코의 뒤쪽 반 코에만 바늘을 넣어 뜹니다. 코수는 변하지 않습니다. 도안에는 BLO로 표기합니다.'),
  ('crochet', 'crab', '새우뜨기', 'stitch', 1, '진행 방향을 거꾸로 뜨는 짧은뜨기. 테두리를 단단히 마무리할 때 씁니다. 역짧은뜨기. 도안에는 rev sc 또는 crab st로 표기합니다.'),
  ('crochet', 'color_change', '배색', 'technique', null::int, '실 색을 바꾸는 방법. 직전 코의 마지막 실을 빼낼 때 새 실로 바꾸면 경계가 깔끔합니다.'),
  ('crochet', 'oval_base', '타원형 만들기', 'technique', null::int, '기초 사슬의 양옆을 둘러 뜨며 타원형 밑판을 만드는 방법입니다.'),
  ('crochet', 'ring_base', '사슬 원형코 만들기', 'technique', null::int, '사슬을 이어 고리를 만들고 그 안에 떠 넣는 원형 시작 방법. 매직링(mr)과 달리 중앙에 구멍이 남습니다.'),
  ('crochet', 'sew_finish', '돗바늘 마무리', 'technique', null::int, '돗바늘로 실 끝을 편물 안에 감추거나 편물끼리 잇는 마무리 과정입니다.'),
  ('knitting', 'k', '겉뜨기', 'stitch', 1, '가장 기본이 되는 대바늘 기법. 겉면이 브이(V) 모양으로 보입니다.'),
  ('knitting', 'p', '안뜨기', 'stitch', 1, '겉뜨기의 반대 방향으로 뜨는 기법. 겉면이 가로줄 모양으로 보입니다.'),
  ('knitting', 'yo', '바늘비우기', 'stitch', 1, '실을 바늘에 걸어 구멍과 함께 1코를 늘립니다. 레이스 무늬의 기본입니다.'),
  ('knitting', 'k2tog', '오른코 겹쳐 2코 모아뜨기', 'stitch', 1, '2코를 함께 겉뜨기해 1코로 줄입니다. 오른쪽으로 기웁니다. 왼쪽으로 기우는 ssk(왼코 겹쳐 2코 모아뜨기)와 짝을 이룹니다.'),
  ('knitting', 'ssk', '왼코 겹쳐 2코 모아뜨기', 'stitch', 1, '2코를 겉뜨기 방향으로 옮긴 뒤 함께 떠 1코로 줄입니다. 왼쪽으로 기웁니다. 오른쪽으로 기우는 k2tog(오른코 겹쳐 2코 모아뜨기)와 짝을 이룹니다.'),
  ('knitting', 'co', '코잡기', 'stitch', 1, '대바늘 뜨기를 시작할 때 첫 단의 코를 만드는 과정입니다. 도안에는 CO로 표기합니다.')
) as v(craft_type, standard_code, kr_name, entry_type, stitch_delta, description)
where t.craft_type::text = v.craft_type
  and t.standard_code    = v.standard_code;


-- ------------------------------------------------------------
-- 확인
-- ------------------------------------------------------------
-- 이번에 바뀐 항목이 제대로 들어갔는지
select standard_code, kr_name, description
from craft_terms
where standard_code in ('k2tog','ssk','ring_base','mr','puff','bobble','popcorn')
order by craft_type, standard_code;

-- 영상 링크는 보존되었는지 (직접 채우신 값)
select count(*) filter (where video_url is not null) as 영상_있음,
       count(*) filter (where video_url is null)     as 영상_없음
from craft_terms;
