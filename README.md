# Dipu Turf Champion

A single-turf booking and operations platform built with Python, Django, and MySQL. It combines a public booking page for players with a private mobile-friendly workspace for the owner and staff.

## Features

### For players

- Public turf page with editable contact details, map link, photos, fields, rates, and opening hours.
- Live field availability and custom slot lengths, including bookings that continue after midnight.
- Accountless bookings with team/player details, suggested advance, optional transfer reference, and a private booking reference.
- Booking lookup by reference and phone, including confirmation and payment status, paid total, and due amount.
- QR code entry point for sharing the booking page.
- Installable mobile web app with an app icon, standalone display, and cached app styles.

### For the turf owner and staff

- Booking dashboard with search, date/status filters, a seven-day collection chart, and booking status actions.
- Add walk-in/phone bookings, reschedule bookings, confirm or complete games, and mark no-shows/cancellations.
- Payment ledger for advances, additional payments, transfer verification, and refunds. The app records transactions; owners verify transfers manually.
- Availability board by field, maintenance blocks, full-turf closures, and weekly operating hours including overnight hours.
- Multiple fields, field details, minimum booking time, and per-field slot intervals.
- Weekday, weekend, peak-time, selected-weekday, and special-date prices.
- Customer records with booking history, contact links, owner notes, and verified paid totals.
- Expense tracking, net collection reports, CSV and Excel exports.
- Public profile settings, map coordinates, payment instructions, logo, and up to 12 optimized gallery photos.
- Staff accounts, separate booking/payment/settings permissions, activity history, and password changes.
- Django admin for direct data management.

Card payments and automatic bKash/Nagad verification are not configured. Payment providers need merchant credentials and integration before they can process money automatically. SMS/WhatsApp notifications are not included.

## Local setup

Use Python 3.12 and MySQL 8.4. Docker Compose starts the database; `.env.example` lists the settings to copy and adjust.

```powershell
Copy-Item .env.example .env
docker compose up -d db
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` for the public page, `/owner/` for the owner workspace, and `/django-admin/` for Django admin. Sign in with the Django staff/superuser account created above. You can also leave `MYSQL_DATABASE` unset to use SQLite for a quick local preview.

Before accepting bookings, update the turf name, contact information, address, fields, operating hours, and rates in the workspace. Configure payment instructions and verify any transfer references manually.

## Deployment

The repository includes a Dockerfile and Render Blueprint. Set `DJANGO_DEBUG=False`, a private `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and a durable MySQL connection in the host environment. Configure persistent storage for `MEDIA_ROOT` so uploaded profile and gallery photos survive redeploys. Render's free web services sleep after 15 minutes without inbound traffic and have a temporary filesystem; the paid web plan is required for an always-on service and is billed separately from the database. Check current prices in the Render dashboard before upgrading.

For an initial owner account, set `OWNER_EMAIL` and a generated `OWNER_TEMP_PASSWORD` (at least 12 characters) in the host's secret environment variables. The container creates a Django superuser with the email as its username after migrations. It never resets an existing owner's password on restart; change the temporary password from **My account** after first sign-in. Django stores a salted password hash, never the plain password. For hosted MySQL, configure either `DATABASE_URL` (`mysql://USER:PASSWORD@HOST:PORT/NAME`, URL-encode special characters) or the individual `MYSQL_*` variables. A free temporary database is not suitable for permanent bookings or a long-lived owner password; connect a persistent MySQL database before moving production data or relying on account changes.
