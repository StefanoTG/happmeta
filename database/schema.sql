-- SubProxy SQLite schema
-- Stores dynamic metadata headers and node rename rules.

CREATE TABLE IF NOT EXISTS metadata (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,   -- header name, e.g. "profile-title"
    value      TEXT NOT NULL,          -- header value
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS node_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type  TEXT NOT NULL,          -- prefix | suffix | regex | emoji | template
    pattern    TEXT,                   -- for regex / template placeholder
    replacement TEXT NOT NULL,         -- value to inject / replace
    enabled    INTEGER NOT NULL DEFAULT 1,
    priority   INTEGER NOT NULL DEFAULT 100,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
