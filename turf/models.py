import secrets
import string
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def generate_qr_token():
    return secrets.token_urlsafe(24)


class TurfProfile(models.Model):
    name = models.CharField(max_length=120, default="Dipu Turf Champion")
    tagline = models.CharField(max_length=180, default="Your home ground for good football")
    address = models.CharField(max_length=240, default="Add your turf address")
    phone = models.CharField(max_length=32, blank=True)
    whatsapp = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    maps_url = models.URLField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    opening_time = models.TimeField(default="07:00")
    closing_time = models.TimeField(default="23:00")
    closes_next_day = models.BooleanField(default=False)
    slot_minutes = models.PositiveSmallIntegerField(default=60)
    weekday_rate = models.PositiveIntegerField(default=1200, help_text="BDT per hour")
    weekend_rate = models.PositiveIntegerField(default=1500, help_text="BDT per hour")
    weekend_days = models.JSONField(default=list, blank=True, help_text="Weekday numbers, Monday is 0. Bangladesh default is Friday and Saturday.")
    advance_percent = models.PositiveSmallIntegerField(default=30)
    booking_instructions = models.TextField(blank=True)
    cancellation_policy = models.TextField(blank=True)
    payment_details = models.TextField(blank=True, help_text="bKash, Nagad, Rocket or bank account instructions for players")
    public_booking_enabled = models.BooleanField(default=True)
    theme_color = models.CharField(max_length=7, default="#37623b")
    profile_picture = models.ImageField(upload_to="turf/profile/", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Turf settings"

    def __str__(self):
        return self.name

    @classmethod
    def current(cls):
        profile, _ = cls.objects.get_or_create(pk=1)
        return profile

    def rate_for(self, play_date):
        weekend_days = self.weekend_days or [4, 5]
        return self.weekend_rate if play_date.weekday() in weekend_days else self.weekday_rate


class TurfField(models.Model):
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=240, blank=True)
    size = models.CharField(max_length=40, blank=True, help_text="For example, 5-a-side or 7-a-side")
    surface = models.CharField(max_length=60, blank=True)
    is_indoor = models.BooleanField(default=False)
    has_lighting = models.BooleanField(default=True)
    slot_granularity_minutes = models.PositiveSmallIntegerField(default=30)
    minimum_minutes = models.PositiveSmallIntegerField(default=60)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class OperatingHours(models.Model):
    WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")]
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS, unique=True)
    opens_at = models.TimeField(default="07:00")
    closes_at = models.TimeField(default="23:00")
    closes_next_day = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ["weekday"]
        verbose_name_plural = "Operating hours"

    def __str__(self):
        return self.get_weekday_display()


class PricingRule(models.Model):
    class Kind(models.TextChoices):
        WEEKDAY = "weekday", "Weekday"
        WEEKEND = "weekend", "Weekend"
        SPECIFIC_DAYS = "days", "Selected weekdays"
        SPECIAL_DATE = "date", "Special date"

    field = models.ForeignKey(TurfField, null=True, blank=True, on_delete=models.CASCADE, related_name="pricing_rules")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.WEEKDAY)
    label = models.CharField(max_length=80, default="Standard rate")
    play_date = models.DateField(null=True, blank=True)
    weekdays = models.JSONField(default=list, blank=True)
    starts_at = models.TimeField(null=True, blank=True)
    ends_at = models.TimeField(null=True, blank=True)
    hourly_rate = models.PositiveIntegerField()
    priority = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-priority", "starts_at"]

    def __str__(self):
        return f"{self.label} · ৳{self.hourly_rate}/h"


class SpecialClosure(models.Model):
    play_date = models.DateField(unique=True)
    title = models.CharField(max_length=120, blank=True)
    is_closed = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.play_date} · {self.title or 'Closure'}"


class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=32, unique=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} · {self.phone}"


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No show"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PENDING_VERIFICATION = "verify", "Payment to verify"
        PARTIAL = "partial", "Deposit received"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"

    class PaymentMethod(models.TextChoices):
        TURF = "at_turf", "Pay at the turf"
        BKASH = "bkash", "bKash"
        NAGAD = "nagad", "Nagad"
        ROCKET = "rocket", "Rocket"
        BANK = "bank", "Bank transfer"

    class Source(models.TextChoices):
        PUBLIC = "public", "Public booking"
        MANUAL = "manual", "Added by owner"

    reference = models.CharField(max_length=16, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="bookings")
    field = models.ForeignKey(TurfField, null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings")
    play_date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    end_day_offset = models.PositiveSmallIntegerField(default=0)
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    team_name = models.CharField(max_length=120, blank=True)
    players = models.PositiveSmallIntegerField(default=0)
    total_amount = models.PositiveIntegerField()
    advance_amount = models.PositiveIntegerField(default=0)
    discount_amount = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.PUBLIC)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment_status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    payment_method = models.CharField(max_length=12, choices=PaymentMethod.choices, default=PaymentMethod.TURF)
    transaction_reference = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    price_snapshot = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_turf_bookings")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="confirmed_turf_bookings")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["play_date", "start_time"]
        indexes = [models.Index(fields=["play_date", "start_time", "status"], name="turf_booking_slot_idx")]

    def save(self, *args, **kwargs):
        if not self.reference:
            alphabet = string.ascii_uppercase + string.digits
            while True:
                candidate = "DTC-" + "".join(secrets.choice(alphabet) for _ in range(8))
                if not Booking.objects.filter(reference=candidate).exists():
                    self.reference = candidate
                    break
        super().save(*args, **kwargs)

    @property
    def paid_amount(self):
        payments = self.payments.all()
        positive = sum((p.amount for p in payments if p.kind != PaymentRecord.Kind.REFUND and p.is_verified), 0)
        refunds = sum((p.amount for p in payments if p.kind == PaymentRecord.Kind.REFUND and p.is_verified), 0)
        return max(positive - refunds, 0)

    @property
    def amount_due(self):
        return max(self.total_amount - self.paid_amount, 0)

    def __str__(self):
        return f"{self.reference} · {self.customer.name}"


class BlockedSlot(models.Model):
    field = models.ForeignKey(TurfField, null=True, blank=True, on_delete=models.CASCADE, related_name="blocked_slots")
    play_date = models.DateField(db_index=True)
    start_time = models.TimeField(null=True, blank=True, help_text="Leave both times blank to block the full day")
    end_time = models.TimeField(null=True, blank=True)
    end_day_offset = models.PositiveSmallIntegerField(default=0)
    reason = models.CharField(max_length=140, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.play_date} · {self.reason or 'Blocked'}"


class PaymentRecord(models.Model):
    class Kind(models.TextChoices):
        ADVANCE = "advance", "Advance"
        PAYMENT = "payment", "Payment"
        REFUND = "refund", "Refund"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    amount = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.PAYMENT)
    method = models.CharField(max_length=40, blank=True)
    transaction_reference = models.CharField(max_length=100, blank=True)
    is_verified = models.BooleanField(default=True)
    received_at = models.DateTimeField(default=timezone.now)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"৳{self.amount} · {self.booking.reference}"


class Expense(models.Model):
    class Category(models.TextChoices):
        MAINTENANCE = "maintenance", "Maintenance"
        STAFF = "staff", "Staff and wages"
        UTILITIES = "utilities", "Utilities"
        EQUIPMENT = "equipment", "Equipment"
        OTHER = "other", "Other"

    date = models.DateField(default=timezone.localdate, db_index=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    description = models.CharField(max_length=180)
    amount = models.PositiveIntegerField()
    receipt_reference = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"৳{self.amount} · {self.description}"


class GalleryPhoto(models.Model):
    image = models.ImageField(upload_to="turf/gallery/")
    caption = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        return self.caption or self.image.name


class WorkspaceMember(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="turf_workspace_membership")
    role = models.CharField(max_length=20, default="manager")
    can_manage_bookings = models.BooleanField(default=True)
    can_manage_payments = models.BooleanField(default=True)
    can_manage_settings = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} · {self.role}"


class ActivityLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=60)
    target_id = models.CharField(max_length=80, blank=True)
    summary = models.CharField(max_length=240)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class BookingQRCode(models.Model):
    token = models.CharField(max_length=40, unique=True, default=generate_qr_token)
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Booking QR · {self.token[:8]}"


def operating_windows(profile, play_date):
    hours = OperatingHours.objects.filter(weekday=play_date.weekday()).first()
    previous_date = play_date - timedelta(days=1)
    previous_hours = OperatingHours.objects.filter(weekday=previous_date.weekday()).first()
    if previous_hours and previous_hours.is_closed:
        previous_hours = None
    previous_open = (previous_hours.opens_at, previous_hours.closes_at, previous_hours.closes_next_day) if previous_hours else (profile.opening_time, profile.closing_time, profile.closes_next_day)
    windows = []
    if previous_open[2] and previous_open[1] <= previous_open[0] and previous_open[1] != time.min:
        windows.append((datetime.combine(play_date, time.min), datetime.combine(play_date, previous_open[1])))
    if hours:
        if hours.is_closed:
            return windows
        start_time, end_time, next_day = hours.opens_at, hours.closes_at, hours.closes_next_day
    else:
        start_time, end_time, next_day = profile.opening_time, profile.closing_time, profile.closes_next_day
    start = datetime.combine(play_date, start_time)
    if next_day and end_time <= start_time:
        windows.append((start, datetime.combine(play_date + timedelta(days=1), end_time)))
        return windows
    end = datetime.combine(play_date + timedelta(days=1 if next_day else 0), end_time)
    if end <= start:
        end += timedelta(days=1)
    windows.append((start, end))
    return windows


def _rate_for(profile, play_date, start, end, field_obj):
    cursor = start
    total = Decimal("0")
    segments = []
    while cursor < end:
        segment_end = min(end, cursor + timedelta(minutes=15))
        base_rate = profile.rate_for(cursor.date())
        rules = PricingRule.objects.filter(is_active=True).filter(models.Q(field__isnull=True) | models.Q(field=field_obj))
        rate, label = base_rate, "Weekend" if cursor.date().weekday() in (profile.weekend_days or [4, 5]) else "Weekday"
        for rule in rules:
            applies = (
                (rule.kind == PricingRule.Kind.SPECIAL_DATE and rule.play_date == cursor.date())
                or (rule.kind == PricingRule.Kind.SPECIFIC_DAYS and cursor.date().weekday() in rule.weekdays)
                or (rule.kind == PricingRule.Kind.WEEKEND and cursor.date().weekday() in (profile.weekend_days or [4, 5]))
                or (rule.kind == PricingRule.Kind.WEEKDAY and cursor.date().weekday() not in (profile.weekend_days or [4, 5]))
            )
            if applies and (rule.starts_at is None or rule.starts_at <= cursor.time()) and (rule.ends_at is None or rule.ends_at > cursor.time()):
                rate, label = rule.hourly_rate, rule.label
                break
        minutes = Decimal(str((segment_end - cursor).total_seconds())) / Decimal("60")
        total += Decimal(rate) * minutes / Decimal("60")
        segments.append({"start": cursor.isoformat(), "end": segment_end.isoformat(), "rate": rate, "label": label})
        cursor = segment_end
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), segments


def build_slots(profile, play_date, field_obj=None, exclude_booking=None):
    field_obj = field_obj or TurfField.objects.filter(is_active=True).first()
    closures = set(SpecialClosure.objects.filter(
        play_date__in=[play_date - timedelta(days=1), play_date, play_date + timedelta(days=1)], is_closed=True
    ).values_list("play_date", flat=True))
    if play_date in closures:
        return []
    windows = operating_windows(profile, play_date)
    if not windows:
        return []
    increment = field_obj.slot_granularity_minutes if field_obj else profile.slot_minutes
    duration = timedelta(minutes=increment)
    lower_date = play_date - timedelta(days=1)
    bookings = Booking.objects.filter(play_date__gte=lower_date, play_date__lte=play_date).exclude(status=Booking.Status.CANCELLED).select_related("field")
    if exclude_booking:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    blocks = BlockedSlot.objects.filter(play_date__gte=lower_date, play_date__lte=play_date).filter(models.Q(field__isnull=True) | models.Q(field=field_obj))
    now = timezone.localtime().replace(tzinfo=None)
    slots = []
    for opening, closing in windows:
      cursor = opening
      while cursor + duration <= closing:
        end = cursor + duration
        if cursor.date() in closures:
            cursor += duration
            continue
        overlaps_booking = False
        for booking in bookings:
            if field_obj and booking.field_id and booking.field_id != field_obj.id:
                continue
            booked_start = datetime.combine(booking.play_date, booking.start_time)
            booked_end = datetime.combine(booking.play_date + timedelta(days=booking.end_day_offset), booking.end_time)
            if booked_start < end and booked_end > cursor:
                overlaps_booking = True
                break
        overlaps_block = False
        for block in blocks:
            if block.start_time is None:
                block_start = datetime.combine(block.play_date, time.min)
                block_end = block_start + timedelta(days=1)
            else:
                block_start = datetime.combine(block.play_date, block.start_time)
                block_end = datetime.combine(block.play_date + timedelta(days=block.end_day_offset), block.end_time)
            if block_start < end and block_end > cursor:
                overlaps_block = True
                break
        is_past = end <= now
        amount, price_snapshot = _rate_for(profile, play_date, cursor, end, field_obj)
        slots.append({
            "start": cursor.time(), "end": end.time(), "date": cursor.date(),
            "start_at": cursor.strftime("%Y-%m-%dT%H:%M"), "end_at": end.strftime("%Y-%m-%dT%H:%M"),
            "end_date": end.date(),
            "end_day_offset": (end.date() - cursor.date()).days,
            "available": not (overlaps_booking or overlaps_block or is_past),
            "price": amount, "price_snapshot": price_snapshot,
            "booking": next((b for b in bookings if datetime.combine(b.play_date, b.start_time) <= cursor < datetime.combine(b.play_date + timedelta(days=b.end_day_offset), b.end_time)), None),
        })
        cursor += duration
    return sorted(slots, key=lambda slot: (slot["date"], slot["start"]))


def validate_booking_slot(profile, play_date, start_time, slot_count=1, field_obj=None, exclude_booking=None):
    slots = build_slots(profile, play_date, field_obj, exclude_booking=exclude_booking)
    first = next((i for i, slot in enumerate(slots) if slot["start"] == start_time), None)
    if first is None or slot_count < 1:
        raise ValidationError("Choose a valid start time and duration.")
    selection = slots[first:first + slot_count]
    if len(selection) != slot_count or any(not slot["available"] for slot in selection):
        raise ValidationError("One or more selected slots are unavailable. Please choose another time.")
    for previous, current in zip(selection, selection[1:]):
        previous_end = datetime.combine(previous["date"] + timedelta(days=previous["end_day_offset"]), previous["end"])
        current_start = datetime.combine(current["date"], current["start"])
        if previous_end != current_start:
            raise ValidationError("Choose a continuous run of open slots.")
    if slot_count * (field_obj.slot_granularity_minutes if field_obj else profile.slot_minutes) < (field_obj.minimum_minutes if field_obj else 0):
        raise ValidationError("This field has a longer minimum booking duration.")
    total = sum(slot["price"] for slot in selection)
    return {
        "start": datetime.combine(play_date, selection[0]["start"]),
        "end": datetime.combine(play_date + timedelta(days=selection[-1]["end_day_offset"]), selection[-1]["end"]),
        "duration_minutes": slot_count * (field_obj.slot_granularity_minutes if field_obj else profile.slot_minutes),
        "price": total,
        "price_snapshot": [segment for slot in selection for segment in slot["price_snapshot"]],
    }
