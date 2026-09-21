CREATE TABLE IF NOT EXISTS mm_queue (
    user_id    TEXT PRIMARY KEY,
    party_id   TEXT NOT NULL DEFAULT '',
    mode       TEXT NOT NULL DEFAULT '2v2',
    status     TEXT NOT NULL DEFAULT 'waiting',   -- waiting | assigned
    match_id   TEXT NOT NULL DEFAULT '',
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mm_queue_status_idx ON mm_queue (mode, status, enqueued_at);

CREATE TABLE IF NOT EXISTS mm_matches (
    id         TEXT PRIMARY KEY,
    mode       TEXT NOT NULL DEFAULT '2v2',
    team_a     JSONB NOT NULL,
    team_b     JSONB NOT NULL,
    status     TEXT NOT NULL DEFAULT 'formed',   -- formed | started | done | cancelled
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
