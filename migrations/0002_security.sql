CREATE TABLE IF NOT EXISTS login_attempts (
  ip_hash TEXT PRIMARY KEY,
  attempts INTEGER NOT NULL DEFAULT 0,
  window_started_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS public_rate_limits (
  scope TEXT NOT NULL,
  ip_hash TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  window_started_at INTEGER NOT NULL,
  PRIMARY KEY(scope, ip_hash)
);
