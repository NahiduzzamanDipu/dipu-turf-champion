import secrets
import string
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TurfProfile(models.Model):
    name = models.CharField(max_length=120, default="Dipu Turf Champion")
    tagline = models.CharField(max_length=180, default="Your home ground for good football")
    address = models.CharField(max_length=240, default="Add your turf address")
    phone = models.CharField(max_length=32, blank=True)
    whatsapp = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    maps_url = models.URLField(blank=True)
    opening_time = models.TimeField(default="07:00")
    closing_time = models.TimeField(default="23:00")
    slot_minutes = models.PositiveSmallIntegerField(default=60)
    weekday_rate = models.PositiveIntegerField(default=1200, help_text="BDT per slot")
    weekend_rate = models.PositiveIntegerField(default=1500, help_text="BDT per slot")
    advance_percent = models.PositiveSmallIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Turf settings"

    def __str__(self):
        return self.name

    @classmethod
    def current(cls):
        profile, _ = cls.objects.get_or_create(pk=1)
        return profile

    def rate_for(self, date):
        return self.weekend_rate if date.weekday() >= 4 else self.weekday_rate


class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=32, unique=True)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} · {self.phone}"


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Deposit received"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"

    class PaymentMethod(models.TextChoices):
        TURF = "at_turf", "Pay at the turf"
        BKASH = "bkash", "bKash / Nagad"
        BANK = "bank", "Bank transfer"

    reference = models.CharField(max_length=12, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="bookings")
    play_date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    total_amount = models.PositiveIntegerField()
    advance_amount = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment_status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    payment_method = models.CharField(max_length=12, choices=PaymentMethod.choices, default=PaymentMethod.TURF)
    transaction_reference = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["play_date", "start_time"]
        indexes = [models.Index(fields=["play_date", "start_time", "status"], name="turf_booking_slot_idx")]

    def save(self, *args, **kwargs):
        if not self.reference:
            alphabet = string.ascii_uppercase + string.digits
            while True:
                candidate = "DTC-" + "".join(secrets.choice(alphabet) for _ in range(6))
                if not Booking.objects.filter(reference=candidate).exists():
                    self.reference = candidate
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} · {self.customer.name}"


class BlockedSlot(models.Model):
    play_date = models.DateField(db_index=True)
    start_time = models.TimeField(null=True, blank=True, help_text="Leave blank to block the full day")
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=140, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.play_date} · {self.reason or 'Blocked'}"


class PaymentRecord(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    amount = models.PositiveIntegerField()
    method = models.CharField(max_length=40, blank=True)
    transaction_reference = models.CharField(max_length=100, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"৳{self.amount} · {self.booking.reference}"


def build_slots(profile, play_date):
    opening = datetime.combine(play_date, profile.opening_time)
    closing = datetime.combine(play_date, profile.closing_time)
    duration = timedelta(minutes=profile.slot_minutes)
    bookings = Booking.objects.filter(play_date=play_date).exclude(status=Booking.Status.CANCELLED)
    blocked = list(BlockedSlot.objects.filter(play_date=play_date))
    slots = []
    cursor = opening
    while cursor + duration <= closing:
        end = cursor + duration
        overlaps_booking = bookings.filter(start_time__lt=end.time(), end_time__gt=cursor.time()).exists()
        overlaps_block = any(
            block.start_time is None
            or (block.start_time < end.time() and block.end_time and block.end_time > cursor.time())
            for block in blocked
        )
        is_past = timezone.localtime().date() == play_date and cursor.time() <= timezone.localtime().time()
        slots.append({
            "start": cursor.time(), "end": end.time(), "available": not (overlaps_booking or overlaps_block or is_past),
            "price": profile.rate_for(play_date),
        })
        cursor += duration
    return slots


def validate_booking_slot(profile, play_date, start_time):
    slots = build_slots(profile, play_date)
    slot = next((item for item in slots if item["start"] == start_time), None)
    if not slot or not slot["available"]:
        raise ValidationError("That slot has just been taken. Please choose another time.")
    return slot
