import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = "Create the initial turf owner from OWNER_EMAIL and OWNER_TEMP_PASSWORD."

    def handle(self, *args, **options):
        email = os.getenv("OWNER_EMAIL", "").strip()
        password = os.getenv("OWNER_TEMP_PASSWORD", "")
        if not email and not password:
            self.stdout.write("Initial owner setup skipped; no owner credentials configured.")
            return
        if not email or not password:
            raise CommandError("Set both OWNER_EMAIL and OWNER_TEMP_PASSWORD for initial owner setup.")
        if len(password) < 12:
            raise CommandError("OWNER_TEMP_PASSWORD must be at least 12 characters long.")
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("OWNER_EMAIL must be a valid email address.") from exc

        User = get_user_model()
        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            if existing.username.casefold() == email.casefold() and existing.is_staff and existing.is_superuser:
                self.stdout.write(f"Owner account {email} already exists; password left unchanged.")
                return
            raise CommandError(f"An account with {email} already exists; refusing to change its access or password.")
        if User.objects.filter(username__iexact=email).exists():
            raise CommandError(f"Username {email} is already taken by a different account.")

        User.objects.create_superuser(username=email, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created initial owner account {email}."))
