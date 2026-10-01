CREATE TABLE email_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), enabled BOOLEAN NOT NULL DEFAULT false,
 sender TEXT, client_id TEXT, refresh_token_cipher TEXT,
 connection_status TEXT NOT NULL DEFAULT 'disconnected', connection_revision INTEGER NOT NULL DEFAULT 0,
 test_accepted_at TIMESTAMPTZ, connected_at TIMESTAMPTZ, worker_seen_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO email_settings(id) VALUES(1);
CREATE TABLE email_oauth_states (
 state_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 session_hash TEXT NOT NULL, verifier_cipher TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE email_events (
 id BIGSERIAL PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
 product_id INTEGER REFERENCES products(id), payload JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE email_messages (
 id BIGSERIAL PRIMARY KEY, event_id BIGINT NOT NULL REFERENCES email_events(id) ON DELETE CASCADE,
 user_id INTEGER REFERENCES users(id), recipient TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','accepted','failed','uncertain','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 claimed_at TIMESTAMPTZ, accepted_at TIMESTAMPTZ, provider_id TEXT, last_error TEXT,
 connection_revision INTEGER, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(event_id,recipient)
);
CREATE INDEX email_pending_idx ON email_messages(next_attempt_at,id) WHERE status='pending';
CREATE INDEX email_history_idx ON email_messages(id DESC);
CREATE TABLE email_attempts (
 id BIGSERIAL PRIMARY KEY, message_id BIGINT REFERENCES email_messages(id) ON DELETE SET NULL,
 started_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX email_attempts_time_idx ON email_attempts(started_at);
