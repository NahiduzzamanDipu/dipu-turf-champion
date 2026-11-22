# Dipu Turf Champion

A branded football turf website with public booking requests, a live availability view, customer booking lookup, and a private owner dashboard.

## Features

- English and Bengali public pages for the home, about, turf, pricing, gallery, booking, contact, terms, and privacy sections.
- Date-based opening hours and slot availability; bookings are protected against duplicate reservations.
- Owner dashboard for booking status and payment records, manual bookings, customers, notifications, blocked slots, opening hours, site content, pricing, and CSV exports.
- Owner password hashing, signed secure sessions, login throttling, audit records, and rate limits.
- PostgreSQL stores bookings, settings, and uploaded gallery images.

## Run locally

Requires Node.js 20 or later and npm. Create a PostgreSQL database and configure `.env` using `.env.example` as a guide.

```powershell
npm.cmd install
npm.cmd run dev
```

The Vite server handles the public UI. To run the complete site including APIs, start the production server after building:

```powershell
npm.cmd run build
npm.cmd start
```

On first server start, the app applies the idempotent SQL migrations from `migrations/`.

## Deploy free on Render

The repository contains a Render Blueprint (`render.yaml`) for a free Node web service. It requires a PostgreSQL URL; use a free external PostgreSQL provider such as Neon. Render's free PostgreSQL database expires after 30 days, so it is not used here.

1. Create a PostgreSQL project on Neon and copy its pooled connection string. Ensure SSL is enabled.
2. Create a private GitHub repository and push this project.
3. In Render, choose **New → Blueprint**, connect the GitHub repository, and deploy `render.yaml`.
4. When prompted, enter `DATABASE_URL`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD_HASH`. Create the password hash locally with `node scripts/hash-password.mjs`; use a unique password of at least 12 characters. Render generates `SESSION_SECRET` automatically.
5. Open the resulting `*.onrender.com` URL. Sign in at `/admin` and set accurate prices, phone/WhatsApp, address, map link, opening hours, photos, policies, and terms before accepting bookings.

Render's free web service spins down after 15 minutes without traffic and can take about a minute to respond after sleeping. Neon free compute also scales to zero after 5 minutes of database inactivity. Free tiers have quotas and provider terms can change; check current limits before relying on the site for time-sensitive bookings. Render describes its free instances as unsuitable for production use. The app stores uploaded images in PostgreSQL, so keep uploads modest and export booking data regularly.

## Important first-run setup

- Rates start at zero, so customers cannot book until the owner sets prices.
- Replace sample pitch photos with photos the business is allowed to use.
- Add the real business contact details, location, opening hours, map link, and legal copy.
- Customer notifications are recorded in the dashboard only; the app does not send SMS or WhatsApp.
- Payment transfers are not verified automatically. The owner must check each transfer with the payment provider before marking it paid.
- The dashboard exports CSV; payment gateways, SMS/WhatsApp, and `.xlsx` export are not connected.

## Useful files

- `src/main.tsx` — public site and owner dashboard.
- `src/style.css` — responsive visual design.
- `functions/api/[[path]].ts` — booking, availability, sign-in, and dashboard API.
- `server/index.mjs` — Node/Express host and PostgreSQL compatibility layer.
- `migrations/` — PostgreSQL schema, automatically applied at service startup.
- `render.yaml` — Render Blueprint deployment configuration.
