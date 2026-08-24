-- 도안 수정 이력 (pattern_revisions)
--
-- 사용자의 수정은 지금까지처럼 **즉시 반영**된다. 승인을 기다리게 하면
-- 오탈자 하나 고치는 데도 운영자를 거쳐야 해서 아무도 고치지 않게 된다.
-- 대신 무엇이 어떻게 바뀌었는지를 남겨 **운영자가 나중에 훑어보고 되돌릴 수 있게** 한다.
--
-- `PUT /api/pattern/{id}`에는 아직 인증이 없다. 이 표가 그 구멍을 막아 주지는 않지만,
-- "누가 뭘 덮어썼는지 알 수 없고 되돌릴 방법도 없다"는 상태는 끝난다.
-- (docs/ROADMAP.md 병행 과제 · docs/FEATURES.md 6.4)

CREATE TABLE IF NOT EXISTS pattern_revisions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_id   uuid NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,

    -- 수정 직전 / 직후의 도안 본문 전체. 되돌리기는 before를 그대로 되쓴다.
    before       jsonb NOT NULL,
    after        jsonb NOT NULL,

    -- 사람이 훑어보기 위한 요약. "3단 코수 24 → 26" 같은 줄이 담긴다.
    -- 본문 전체를 눈으로 비교하게 만들면 아무도 확인하지 않는다.
    summary      text,
    change_count integer NOT NULL DEFAULT 0,

    -- 누가 고쳤는지. 로그인이 없으므로 IP를 그대로 두지 않고 해시만 남긴다.
    editor_hash  text,

    reverted_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- 한 도안의 이력을 최신순으로 넘기는 조회가 전부다.
CREATE INDEX IF NOT EXISTS idx_pattern_revisions_pattern
    ON pattern_revisions (pattern_id, created_at DESC);

-- 운영자가 "최근 수정 전체"를 훑을 때 쓴다.
CREATE INDEX IF NOT EXISTS idx_pattern_revisions_recent
    ON pattern_revisions (created_at DESC);

-- 이력은 서버(service key)만 읽고 쓴다. 브라우저에 열어 주지 않는다.
ALTER TABLE pattern_revisions ENABLE ROW LEVEL SECURITY;
