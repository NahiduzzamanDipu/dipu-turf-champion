# Dipu Turf Champion

A mobile-first turf booking and owner management platform built with Python, Django, and MySQL.

## What is included

- Public turf page with editable business details and live one-hour slot availability.
- Player booking requests, booking references, and booking lookup by reference and phone number.
- Owner workspace for booking status, payment records, payment totals, CSV export, operating hours, rates, and blocked dates or times.
- Django admin for managing turf settings, customers, bookings, and payment records.
- Responsive desktop and mobile layouts, including a compact mobile navigation dock.
- MySQL setup for local development and deployment, with SQLite available when MySQL variables are not configured.

## Run locally

Use Python 3.12, MySQL 8.4, and a virtual environment. The included Compose file starts a local MySQL database.

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

Set `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, and `MYSQL_PORT` in `.env`. The Compose defaults are for local development only. Set `DJANGO_SECRET_KEY` to a private random value before deployment. If you want to explore with SQLite, leave `MYSQL_DATABASE` unset.

Open `http://127.0.0.1:8000/` for the public site, `/owner/` for the owner workspace, and `/django-admin/` for Django admin. Sign in to the owner workspace with a Django staff or superuser account.

## Deploy

The repository includes a Dockerfile and Render Blueprint. Configure a reachable MySQL database and provide its connection values as environment variables. Set `DJANGO_ALLOWED_HOSTS` to the deployed host name(s) and `CSRF_TRUSTED_ORIGINS` to the corresponding `https://` origin(s). Keep `DJANGO_DEBUG=False` and a private `DJANGO_SECRET_KEY` in production.

Before taking live bookings, sign in to the owner workspace and replace the example address and rates with the turf's real details. Payment entries are recorded by the owner; this project does not initiate or verify bKash, Nagad, card, or bank transfers.

The visual polish pass follows the Unslop design guidance by Damir Sokolovsky, CC BY 4.0.
