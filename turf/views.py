from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import (
    Booking, BookingQRCode, Customer, GalleryPhoto, OperatingHours, SpecialClosure,
    TurfField, TurfProfile, build_slots, validate_booking_slot,
)


def home(request):
    profile = TurfProfile.current()
    selected_date = timezone.localdate() + timedelta(days=1)
    field_obj = TurfField.objects.filter(is_active=True).first()
    slots = [slot for slot in build_slots(profile, selected_date, field_obj) if slot["date"] == selected_date]
    return render(request, "turf/home.html", {
        "profile": profile,
        "featured_slots": [s for s in slots if s["available"] and s["date"] == selected_date][:4],
        "fields": TurfField.objects.filter(is_active=True),
        "photos": GalleryPhoto.objects.filter(is_visible=True)[:12],
        "hours": OperatingHours.objects.all(),
    })


def _selected_field(fields, requested_id):
    if requested_id and str(requested_id).isdecimal():
        return fields.filter(pk=int(requested_id)).first() or fields.first()
    return fields.first()


def book(request):
    profile = TurfProfile.current()
    fields = TurfField.objects.filter(is_active=True)
    requested_field = request.GET.get("field") or request.POST.get("field")
    selected_field = _selected_field(fields, requested_field)
    default_date = timezone.localdate() + timedelta(days=1)
    try:
        date_value = request.GET.get("date") or request.POST.get("date")
        selected_date = date.fromisoformat(date_value) if date_value else default_date
    except ValueError:
        selected_date = default_date
    selected_date = max(selected_date, timezone.localdate())
    slots = build_slots(profile, selected_date, selected_field)
    if request.method == "POST":
        try:
            if not profile.public_booking_enabled:
                raise ValidationError("Online booking is paused. Please contact the turf team.")
            selected_start = datetime.fromisoformat(request.POST.get("start_at", ""))
            play_date = selected_start.date()
            if play_date < timezone.localdate():
                raise ValidationError("Choose today or a future date for your game.")
            selected_field = TurfField.objects.get(pk=request.POST.get("field"), is_active=True)
            start = selected_start.time()
            slot_count = int(request.POST.get("slot_count", "1"))
            name = request.POST.get("name", "").strip()[:100]
            phone = request.POST.get("phone", "").strip()[:32]
            team_name = request.POST.get("team_name", "").strip()[:120]
            payment_method = request.POST.get("payment_method", Booking.PaymentMethod.TURF)
            transaction_ref = request.POST.get("transaction_reference", "").strip()[:100]
            players = int(request.POST.get("players", "0") or 0)
            if not name or len(phone) < 7:
                raise ValidationError("Add your name and a valid mobile number.")
            if payment_method not in Booking.PaymentMethod.values:
                raise ValidationError("Choose a payment method.")
            if players < 0 or players > 50:
                raise ValidationError("Player count must be between 0 and 50.")
            if transaction_ref and payment_method == Booking.PaymentMethod.TURF:
                raise ValidationError("Select the transfer method used for this reference.")
            with transaction.atomic():
                profile = TurfProfile.objects.select_for_update().get(pk=1)
                quote = validate_booking_slot(profile, play_date, start, slot_count, selected_field)
                customer, _ = Customer.objects.get_or_create(phone=phone, defaults={"name": name})
                if customer.name != name:
                    customer.name = name
                    customer.save(update_fields=["name", "updated_at"])
                advance = round(quote["price"] * profile.advance_percent / 100)
                booking = Booking.objects.create(
                    customer=customer, field=selected_field, play_date=play_date,
                    start_time=quote["start"].time(), end_time=quote["end"].time(),
                    end_day_offset=(quote["end"].date() - play_date).days,
                    duration_minutes=quote["duration_minutes"], team_name=team_name,
                    players=players, total_amount=quote["price"],
                    advance_amount=advance, payment_method=payment_method,
                    transaction_reference=transaction_ref,
                    payment_status=Booking.PaymentStatus.PENDING_VERIFICATION if transaction_ref else Booking.PaymentStatus.UNPAID,
                    notes=request.POST.get("notes", "").strip()[:500], price_snapshot=quote["price_snapshot"],
                )
                if transaction_ref:
                    from .models import PaymentRecord
                    PaymentRecord.objects.create(
                        booking=booking, amount=advance, kind=PaymentRecord.Kind.ADVANCE,
                        method=payment_method, transaction_reference=transaction_ref,
                        is_verified=False, note="Player submitted transaction reference for owner verification.",
                    )
            return render(request, "turf/booking_success.html", {"profile": profile, "booking": booking})
        except (ValueError, ValidationError, TurfField.DoesNotExist, TurfProfile.DoesNotExist) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, ValidationError) else "Choose a valid date, field and time.")
            slots = build_slots(profile, selected_date, selected_field)
    return render(request, "turf/book.html", {
        "profile": profile, "fields": fields, "selected_field": selected_field,
        "selected_date": selected_date, "slots": slots,
        "min_date": timezone.localdate().isoformat(),
        "payment_methods": Booking.PaymentMethod.choices,
        "min_slot_count": max(1, (selected_field.minimum_minutes + selected_field.slot_granularity_minutes - 1) // selected_field.slot_granularity_minutes) if selected_field else 1,
        "slot_count_options": range(max(1, (selected_field.minimum_minutes + selected_field.slot_granularity_minutes - 1) // selected_field.slot_granularity_minutes), 17) if selected_field else range(1, 17),
    })


def booking_lookup(request):
    profile = TurfProfile.current()
    booking = None
    if request.method == "POST":
        booking = Booking.objects.filter(
            reference__iexact=request.POST.get("reference", "").strip(),
            customer__phone=request.POST.get("phone", "").strip(),
        ).select_related("customer", "field").first()
        if not booking:
            messages.error(request, "We could not find a booking with those details.")
    return render(request, "turf/lookup.html", {"profile": profile, "booking": booking})


def owner_login(request):
    if request.user.is_authenticated and _is_workspace_user(request.user):
        return redirect("owner_dashboard")
    if request.method == "POST":
        user = authenticate(request, username=request.POST.get("username", ""), password=request.POST.get("password", ""))
        if user and _is_workspace_user(user):
            login(request, user)
            return redirect("owner_dashboard")
        messages.error(request, "Those sign-in details did not match an owner or manager account.")
    return render(request, "turf/owner_login.html", {"profile": TurfProfile.current()})


def owner_logout(request):
    if request.method == "POST":
        logout(request)
    return redirect("home")


def _is_workspace_user(user):
    if user.is_staff or user.is_superuser:
        return True
    try:
        return user.turf_workspace_membership.is_active
    except ObjectDoesNotExist:
        return False


def public_qr(request, token):
    qr = BookingQRCode.objects.filter(token=token, is_active=True).first()
    if not qr:
        from django.http import HttpResponseGone
        return HttpResponseGone("This turf booking QR code has been retired.")
    return redirect("book")
