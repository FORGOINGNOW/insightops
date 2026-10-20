PRAGMA foreign_keys = ON;
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    channel TEXT NOT NULL CHECK(channel IN ('organic','paid')),
    device TEXT NOT NULL,
    is_new INTEGER NOT NULL CHECK(is_new IN (0,1))
);
CREATE TABLE assignments (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
    variant TEXT NOT NULL CHECK(variant IN ('A','B'))
);
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    period TEXT NOT NULL CHECK(period IN ('before','after')),
    occurred_at TEXT NOT NULL
);
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    logical_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE REFERENCES sessions(session_id),
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    refunded INTEGER NOT NULL CHECK(refunded IN (0,1))
);
CREATE TABLE order_items (
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    line_no INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    PRIMARY KEY(order_id,line_no)
);
CREATE INDEX idx_events_session_type ON events(session_id,event_type);
CREATE INDEX idx_events_received ON events(received_at);
CREATE INDEX idx_sessions_period_user ON sessions(period,user_id);

-- Business truth for this fixture: a session converts iff a paid order exists.
-- Events can be duplicated, delayed or missing. Never use raw event rows as sessions.
CREATE VIEW session_facts AS
SELECT s.session_id,s.user_id,s.period,s.occurred_at,u.channel,u.device,u.is_new,
       a.variant,CASE WHEN o.order_id IS NULL THEN 0 ELSE 1 END AS converted,
       COALESCE(o.amount_cents,0) AS revenue_cents,COALESCE(o.refunded,0) AS refunded
FROM sessions s JOIN users u USING(user_id) JOIN assignments a USING(user_id)
LEFT JOIN orders o USING(session_id);
