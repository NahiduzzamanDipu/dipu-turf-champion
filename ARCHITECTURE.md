# Dipu Turf Champion — architecture

## Product

A single football ground business website with customer booking and a private owner dashboard.

## Direction

- **Character:** grounded, energetic, welcoming.
- **World:** an evening football ground, dark touchline greens, worn chalk, and a sharp lime match-day detail.
- **Rich moments:** the floodlit pitch in the hero and the booking slot picker.
- **Typography:** Manrope for strong headings and DM Sans for reading and controls.

## Architecture

- React and TypeScript with Vite build the public site and responsive owner dashboard.
- Express serves the built site and forwards `/api/*` to the TypeScript API handler.
- A small adapter implements the D1 query shape over PostgreSQL, allowing the booking API to run on Render without Cloudflare-specific services.
- PostgreSQL stores all records and uploaded photos as bytea objects.
- The partial unique booking index and API overlap checks prevent active reservations from taking the same slot.
- Owner passwords use PBKDF2-SHA-256. Successful sign-in creates a signed, eight-hour, Secure, HttpOnly, SameSite=Strict cookie.
- Payment remains unpaid until the owner reviews the transfer and records its reference.

## Schema

See `migrations/0001_initial.sql` and `migrations/0002_security.sql`.

| Table | Purpose |
| --- | --- |
| `customers` | Customer name and unique mobile number |
| `bookings` | Ground, slot, amount, payment state, booking status, and notes |
| `pricing` | Weekday, weekend, peak rate, and advance percentage |
| `operating_hours` | Weekly opening hours |
| `blocked_slots` | Full-day or time-window closure |
| `website_content` | Owner-managed copy, contact details, facilities, policies, and gallery |
| `notifications` | In-app booking events; no claimed SMS delivery |
| `audit_log` | Owner action history |
| `login_attempts` | Per-IP sign-in throttling |
| `public_rate_limits` | Hashed-IP booking and lookup rate limits |
| `media_objects` | Owner-uploaded photo bytes and content types |

## Scope and setup

The dashboard includes booking and payment administration, manual bookings, customer records, calendar availability, site content, prices, and CSV export. Payment gateways, SMS/WhatsApp notifications, and spreadsheet exports are not connected. Business rates, phone, address, photos, hours, and policy content need to be completed by the owner before launch.

The Render service uses the free Node web tier and an external PostgreSQL service. Render free web services sleep when idle; free Render PostgreSQL is intentionally not used because it expires after 30 days. Review `README.md` for deployment instructions and current operational limitations.
