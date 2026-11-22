CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  phone TEXT NOT NULL UNIQUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bookings (
  id TEXT PRIMARY KEY,
  reference TEXT NOT NULL UNIQUE,
  customer_id TEXT NOT NULL REFERENCES customers(id),
  ground_id TEXT NOT NULL DEFAULT 'main',
  play_date TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  hours INTEGER NOT NULL DEFAULT 1 CHECK(hours BETWEEN 1 AND 4),
  total_amount INTEGER NOT NULL CHECK(total_amount >= 0),
  advance_amount INTEGER NOT NULL DEFAULT 0 CHECK(advance_amount >= 0),
  payment_method TEXT NOT NULL DEFAULT 'pay-at-turf',
  payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK(payment_status IN ('unpaid','partial','paid','refunded')),
  transaction_reference TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected','cancelled','completed')),
  notes TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_active_booking_slot
  ON bookings(ground_id, play_date, start_time)
  WHERE status IN ('pending', 'confirmed', 'completed');
CREATE INDEX IF NOT EXISTS bookings_date_status ON bookings(play_date, status);
CREATE INDEX IF NOT EXISTS bookings_customer ON bookings(customer_id);

CREATE TABLE IF NOT EXISTS pricing (
  id TEXT PRIMARY KEY DEFAULT 'default',
  weekday_hourly INTEGER NOT NULL DEFAULT 0 CHECK(weekday_hourly >= 0),
  weekend_hourly INTEGER NOT NULL DEFAULT 0 CHECK(weekend_hourly >= 0),
  peak_hourly INTEGER NOT NULL DEFAULT 0 CHECK(peak_hourly >= 0),
  peak_start TEXT NOT NULL DEFAULT '18:00',
  peak_end TEXT NOT NULL DEFAULT '22:00',
  advance_percent INTEGER NOT NULL DEFAULT 0 CHECK(advance_percent BETWEEN 0 AND 100),
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO pricing(id) VALUES ('default') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS operating_hours (
  weekday INTEGER PRIMARY KEY CHECK(weekday BETWEEN 0 AND 6),
  opens_at TEXT NOT NULL DEFAULT '08:00',
  closes_at TEXT NOT NULL DEFAULT '23:00',
  is_open INTEGER NOT NULL DEFAULT 1
);
INSERT INTO operating_hours(weekday) VALUES (0),(1),(2),(3),(4),(5),(6) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS blocked_slots (
  id TEXT PRIMARY KEY,
  play_date TEXT NOT NULL,
  start_time TEXT,
  end_time TEXT,
  reason TEXT NOT NULL DEFAULT 'Unavailable',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS blocked_slots_date ON blocked_slots(play_date);

CREATE TABLE IF NOT EXISTS website_content (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  details TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  booking_id TEXT REFERENCES bookings(id),
  message TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'in-app',
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','sent','failed')),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS media_objects (
  key TEXT PRIMARY KEY,
  content BYTEA NOT NULL,
  content_type TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
