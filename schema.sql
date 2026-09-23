CREATE TABLE IF NOT EXISTS mm_queue (
    user_id    TEXT PRIMARY KEY,
    party_id   TEXT NOT NULL DEFAULT '',
    mode       TEXT NOT NULL DEFAULT '2v2',
    status     TEXT NOT NULL DEFAULT 'waiting',   -- waiting | assigned
    match_id   TEXT NOT NULL DEFAULT '',
    source_server_id TEXT NOT NULL DEFAULT '',
    source_place_id BIGINT NOT NULL DEFAULT 0,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE mm_queue ADD COLUMN IF NOT EXISTS source_server_id TEXT NOT NULL DEFAULT '';
ALTER TABLE mm_queue ADD COLUMN IF NOT EXISTS source_place_id BIGINT NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS mm_queue_status_idx ON mm_queue (mode, status, enqueued_at);

CREATE TABLE IF NOT EXISTS mm_matches (
    id         TEXT PRIMARY KEY,
    mode       TEXT NOT NULL DEFAULT '2v2',
    team_a     JSONB NOT NULL,
    team_b     JSONB NOT NULL,
    status     TEXT NOT NULL DEFAULT 'formed',   -- formed | started | done | cancelled
    destination_place_id BIGINT,
    reservation_state TEXT NOT NULL DEFAULT 'pending', -- pending | claimed | ready
    reservation_owner_server_id TEXT NOT NULL DEFAULT '',
    reservation_token TEXT NOT NULL DEFAULT '',
    reservation_claim_expires_at TIMESTAMPTZ,
    reserved_server_code TEXT NOT NULL DEFAULT '',
    private_server_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE mm_matches ADD COLUMN IF NOT EXISTS destination_place_id BIGINT;
ALTER TABLE mm_matches ADD COLUMN IF NOT EXISTS reservation_state TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE mm_matches ADD COLUMN IF NOT EXISTS reservation_owner_server_id TEXT NOT NULL DEFAULT '';
ALTER TABLE mm_matches ADD COLUMN IF NOT EXISTS reservation_token TEXT NOT NULL DEFAULT '';
ALTER TABLE mm_matches ADD COLUMN IF NOT EXISTS reservation_claim_expires_at TIMESTAMPTZ;
ALTER TABLE mm_matches ADD COLUMN IF NOT EXISTS reserved_server_code TEXT NOT NULL DEFAULT '';
ALTER TABLE mm_matches ADD COLUMN IF NOT EXISTS private_server_id TEXT NOT NULL DEFAULT '';
