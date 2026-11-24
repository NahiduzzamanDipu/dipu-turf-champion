import django.db.models.deletion
import django.utils.timezone
import turf.models
from django.conf import settings
from django.db import migrations, models


def add_default_field_and_hours(apps, schema_editor):
    Profile = apps.get_model("turf", "TurfProfile")
    Field = apps.get_model("turf", "TurfField")
    Hours = apps.get_model("turf", "OperatingHours")
    profile = Profile.objects.filter(pk=1).first()
    Field.objects.get_or_create(pk=1, defaults={"name": "Main field", "description": "The home pitch", "size": "5-a-side", "surface": "Artificial grass", "slot_granularity_minutes": 60, "minimum_minutes": 60, "is_active": True, "sort_order": 0})
    opens = profile.opening_time if profile else "07:00"
    closes = profile.closing_time if profile else "23:00"
    next_day = profile.closes_next_day if profile else False
    Hours.objects.bulk_create([
        Hours(weekday=day, opens_at=opens, closes_at=closes, closes_next_day=next_day, is_closed=False)
        for day in range(7)
    ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("turf", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField("turfprofile", "latitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField("turfprofile", "longitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField("turfprofile", "closes_next_day", models.BooleanField(default=False)),
        migrations.AddField("turfprofile", "weekend_days", models.JSONField(blank=True, default=list, help_text="Weekday numbers, Monday is 0. Bangladesh default is Friday and Saturday.")),
        migrations.AddField("turfprofile", "booking_instructions", models.TextField(blank=True)),
        migrations.AddField("turfprofile", "cancellation_policy", models.TextField(blank=True)),
        migrations.AddField("turfprofile", "payment_details", models.TextField(blank=True, help_text="bKash, Nagad, Rocket or bank account instructions for players")),
        migrations.AddField("turfprofile", "public_booking_enabled", models.BooleanField(default=True)),
        migrations.AddField("turfprofile", "theme_color", models.CharField(default="#37623b", max_length=7)),
        migrations.AddField("turfprofile", "profile_picture", models.ImageField(blank=True, upload_to="turf/profile/")),
        migrations.AlterField("turfprofile", "weekday_rate", models.PositiveIntegerField(default=1200, help_text="BDT per hour")),
        migrations.AlterField("turfprofile", "weekend_rate", models.PositiveIntegerField(default=1500, help_text="BDT per hour")),
        migrations.AddField("customer", "notes", models.TextField(blank=True)),
        migrations.AddField("customer", "updated_at", models.DateTimeField(auto_now=True)),
        migrations.CreateModel(
            name="TurfField",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)), ("description", models.CharField(blank=True, max_length=240)),
                ("size", models.CharField(blank=True, help_text="For example, 5-a-side or 7-a-side", max_length=40)),
                ("surface", models.CharField(blank=True, max_length=60)), ("is_indoor", models.BooleanField(default=False)),
                ("has_lighting", models.BooleanField(default=True)), ("slot_granularity_minutes", models.PositiveSmallIntegerField(default=30)),
                ("minimum_minutes", models.PositiveSmallIntegerField(default=60)), ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ], options={"ordering": ["sort_order", "name"]},
        ),
        migrations.CreateModel(
            name="OperatingHours",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("weekday", models.PositiveSmallIntegerField(choices=[(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")], unique=True)),
                ("opens_at", models.TimeField(default="07:00")), ("closes_at", models.TimeField(default="23:00")),
                ("closes_next_day", models.BooleanField(default=False)), ("is_closed", models.BooleanField(default=False)),
            ], options={"ordering": ["weekday"], "verbose_name_plural": "Operating hours"},
        ),
        migrations.CreateModel(
            name="PricingRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("weekday", "Weekday"), ("weekend", "Weekend"), ("days", "Selected weekdays"), ("date", "Special date")], default="weekday", max_length=12)),
                ("label", models.CharField(default="Standard rate", max_length=80)), ("play_date", models.DateField(blank=True, null=True)),
                ("weekdays", models.JSONField(blank=True, default=list)), ("starts_at", models.TimeField(blank=True, null=True)),
                ("ends_at", models.TimeField(blank=True, null=True)), ("hourly_rate", models.PositiveIntegerField()),
                ("priority", models.PositiveSmallIntegerField(default=10)), ("is_active", models.BooleanField(default=True)),
                ("field", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="pricing_rules", to="turf.turffield")),
            ], options={"ordering": ["-priority", "starts_at"]},
        ),
        migrations.CreateModel(
            name="SpecialClosure",
            fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("play_date", models.DateField(unique=True)), ("title", models.CharField(blank=True, max_length=120)), ("is_closed", models.BooleanField(default=True))],
        ),
        migrations.AddField("booking", "field", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bookings", to="turf.turffield")),
        migrations.AddField("booking", "end_day_offset", models.PositiveSmallIntegerField(default=0)),
        migrations.AddField("booking", "duration_minutes", models.PositiveSmallIntegerField(default=60)),
        migrations.AddField("booking", "team_name", models.CharField(blank=True, max_length=120)),
        migrations.AddField("booking", "players", models.PositiveSmallIntegerField(default=0)),
        migrations.AddField("booking", "discount_amount", models.PositiveIntegerField(default=0)),
        migrations.AddField("booking", "source", models.CharField(choices=[("public", "Public booking"), ("manual", "Added by owner")], default="public", max_length=10)),
        migrations.AddField("booking", "price_snapshot", models.JSONField(blank=True, default=list)),
        migrations.AddField("booking", "created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_turf_bookings", to=settings.AUTH_USER_MODEL)),
        migrations.AddField("booking", "confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="confirmed_turf_bookings", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField("booking", "reference", models.CharField(editable=False, max_length=16, unique=True)),
        migrations.AlterField("booking", "status", models.CharField(choices=[("pending", "Awaiting confirmation"), ("confirmed", "Confirmed"), ("completed", "Completed"), ("no_show", "No show"), ("cancelled", "Cancelled")], db_index=True, default="pending", max_length=12)),
        migrations.AlterField("booking", "payment_status", models.CharField(choices=[("unpaid", "Unpaid"), ("verify", "Payment to verify"), ("partial", "Deposit received"), ("paid", "Paid"), ("refunded", "Refunded")], default="unpaid", max_length=12)),
        migrations.AlterField("booking", "payment_method", models.CharField(choices=[("at_turf", "Pay at the turf"), ("bkash", "bKash"), ("nagad", "Nagad"), ("rocket", "Rocket"), ("bank", "Bank transfer")], default="at_turf", max_length=12)),
        migrations.AddField("blockedslot", "field", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="blocked_slots", to="turf.turffield")),
        migrations.AddField("blockedslot", "end_day_offset", models.PositiveSmallIntegerField(default=0)),
        migrations.AddField("paymentrecord", "kind", models.CharField(choices=[("advance", "Advance"), ("payment", "Payment"), ("refund", "Refund")], default="payment", max_length=12)),
        migrations.AddField("paymentrecord", "is_verified", models.BooleanField(default=True)),
        migrations.CreateModel(
            name="Expense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True, default=django.utils.timezone.localdate)),
                ("category", models.CharField(choices=[("maintenance", "Maintenance"), ("staff", "Staff and wages"), ("utilities", "Utilities"), ("equipment", "Equipment"), ("other", "Other")], default="other", max_length=20)),
                ("description", models.CharField(max_length=180)), ("amount", models.PositiveIntegerField()),
                ("receipt_reference", models.CharField(blank=True, max_length=100)), ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-date", "-created_at"]},
        ),
        migrations.CreateModel(
            name="GalleryPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="turf/gallery/")), ("caption", models.CharField(blank=True, max_length=120)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)), ("is_visible", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ], options={"ordering": ["sort_order", "created_at"]},
        ),
        migrations.CreateModel(
            name="WorkspaceMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(default="manager", max_length=20)), ("can_manage_bookings", models.BooleanField(default=True)),
                ("can_manage_payments", models.BooleanField(default=True)), ("can_manage_settings", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="turf_workspace_membership", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=80)), ("target_type", models.CharField(max_length=60)),
                ("target_id", models.CharField(blank=True, max_length=80)), ("summary", models.CharField(max_length=240)),
                ("details", models.JSONField(blank=True, default=dict)), ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="BookingQRCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(default=turf.models.generate_qr_token, max_length=40, unique=True)),
                ("is_active", models.BooleanField(default=True)), ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.RunPython(add_default_field_and_hours, migrations.RunPython.noop),
    ]
