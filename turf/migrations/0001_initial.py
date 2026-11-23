import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("name", models.CharField(max_length=100)), ("phone", models.CharField(max_length=32, unique=True)), ("email", models.EmailField(blank=True, max_length=254)), ("created_at", models.DateTimeField(auto_now_add=True))],
        ),
        migrations.CreateModel(
            name="TurfProfile",
            fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("name", models.CharField(default="Dipu Turf Champion", max_length=120)), ("tagline", models.CharField(default="Your home ground for good football", max_length=180)), ("address", models.CharField(default="Add your turf address", max_length=240)), ("phone", models.CharField(blank=True, max_length=32)), ("whatsapp", models.CharField(blank=True, max_length=32)), ("email", models.EmailField(blank=True, max_length=254)), ("maps_url", models.URLField(blank=True)), ("opening_time", models.TimeField(default="07:00")), ("closing_time", models.TimeField(default="23:00")), ("slot_minutes", models.PositiveSmallIntegerField(default=60)), ("weekday_rate", models.PositiveIntegerField(default=1200, help_text="BDT per slot")), ("weekend_rate", models.PositiveIntegerField(default=1500, help_text="BDT per slot")), ("advance_percent", models.PositiveSmallIntegerField(default=30)), ("updated_at", models.DateTimeField(auto_now=True))],
            options={"verbose_name": "Turf settings"},
        ),
        migrations.CreateModel(
            name="BlockedSlot",
            fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("play_date", models.DateField(db_index=True)), ("start_time", models.TimeField(blank=True, help_text="Leave blank to block the full day", null=True)), ("end_time", models.TimeField(blank=True, null=True)), ("reason", models.CharField(blank=True, max_length=140)), ("created_at", models.DateTimeField(auto_now_add=True)), ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL))],
        ),
        migrations.CreateModel(
            name="Booking",
            fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("reference", models.CharField(editable=False, max_length=12, unique=True)), ("play_date", models.DateField(db_index=True)), ("start_time", models.TimeField()), ("end_time", models.TimeField()), ("total_amount", models.PositiveIntegerField()), ("advance_amount", models.PositiveIntegerField(default=0)), ("status", models.CharField(choices=[("pending", "Awaiting confirmation"), ("confirmed", "Confirmed"), ("completed", "Completed"), ("cancelled", "Cancelled")], db_index=True, default="pending", max_length=12)), ("payment_status", models.CharField(choices=[("unpaid", "Unpaid"), ("partial", "Deposit received"), ("paid", "Paid"), ("refunded", "Refunded")], default="unpaid", max_length=12)), ("payment_method", models.CharField(choices=[("at_turf", "Pay at the turf"), ("bkash", "bKash / Nagad"), ("bank", "Bank transfer")], default="at_turf", max_length=12)), ("transaction_reference", models.CharField(blank=True, max_length=100)), ("notes", models.CharField(blank=True, max_length=500)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)), ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bookings", to="turf.customer"))],
            options={"ordering": ["play_date", "start_time"]},
        ),
        migrations.AddIndex(model_name="booking", index=models.Index(fields=["play_date", "start_time", "status"], name="turf_booking_slot_idx")),
        migrations.CreateModel(
            name="PaymentRecord",
            fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("amount", models.PositiveIntegerField()), ("method", models.CharField(blank=True, max_length=40)), ("transaction_reference", models.CharField(blank=True, max_length=100)), ("received_at", models.DateTimeField(default=django.utils.timezone.now)), ("note", models.CharField(blank=True, max_length=240)), ("booking", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="turf.booking")), ("received_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL))],
            options={"ordering": ["-received_at"]},
        ),
    ]
