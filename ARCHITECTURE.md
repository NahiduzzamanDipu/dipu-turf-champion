# Project structure

- `config/` contains Django settings and the WSGI entry point.
- `turf/` contains the booking, customer, payment, availability, and turf profile models, owner views, and initial MySQL-compatible migration.
- `templates/turf/` contains the public booking pages and owner workspace.
- `static/turf/site.css` contains the responsive visual system and mobile navigation.
- `docker-compose.yml` provides a local MySQL 8.4 service. Django falls back to SQLite only when no MySQL database name is configured.

Booking creation locks the single turf settings row during its availability check and write. Cancelled bookings release their time; other booking states continue to reserve it. Payment records remain an audit trail and update the booking's paid or deposit-received state from the cumulative recorded amount.
