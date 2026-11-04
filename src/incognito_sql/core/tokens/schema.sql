CREATE TABLE IF NOT EXISTS value (
    id INTEGER PRIMARY KEY,
    canon_hash BLOB NOT NULL UNIQUE,
    sealed_canon BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS variant (
    id INTEGER PRIMARY KEY,
    value_id INTEGER NOT NULL REFERENCES value(id),
    domain TEXT NOT NULL,
    raw_hash BLOB NOT NULL,
    sealed_raw BLOB NOT NULL,
    UNIQUE (value_id, domain, raw_hash)
);
CREATE TABLE IF NOT EXISTS token (
    token TEXT PRIMARY KEY,
    value_id INTEGER NOT NULL REFERENCES value(id),
    domain TEXT NOT NULL,
    issued_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS token_lookup ON token (value_id, domain, issued_at);
