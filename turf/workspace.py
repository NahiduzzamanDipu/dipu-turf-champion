import csv
import re
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, Sum, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from .models import (
    ActivityLog, BlockedSlot, Booking, BookingQRCode, Customer, Expense,
    GalleryPhoto, OperatingHours, PaymentRecord, PricingRule, SpecialClosure,
    TurfField, TurfProfile, WorkspaceMember, build_slots, validate_booking_slot,
)


def workspace_required(permission=None):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            member = WorkspaceMember.objects.filter(user=request.user, is_active=True).first()
            if not (request.user.is_staff or request.user.is_superuser or member):
                return redirect("owner_login")
            if permission and member and not getattr(member, f"can_manage_{permission}", False):
                raise PermissionDenied
            request.workspace_member = member
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def _audit(request, action, target, summary, details=None):
    ActivityLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action, target_type=target.__class__.__name__ if target else "Workspace",
        target_id=str(getattr(target, "pk", "")), summary=summary, details=details or {},
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def _selected_dates(request):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("from", "")) if request.GET.get("from") else today.replace(day=1)
        end = date.fromisoformat(request.GET.get("to", "")) if request.GET.get("to") else today
    except ValueError:
        start, end = today.replace(day=1), today
    if end < start:
        start, end = end, start
    return start, end


def _safe_webp_upload(upload):
    if not upload or upload.size > 5 * 1024 * 1024:
        raise ValueError("Choose an image smaller than 5 MB.")
    try:
        source = Image.open(upload)
        source.verify()
        upload.seek(0)
        source = Image.open(upload)
        if source.width > 6000 or source.height > 6000:
            raise ValueError("Image dimensions must be under 6000 × 6000 pixels.")
        source.thumbnail((2400, 2400))
        source = source.convert("RGB")
        output = BytesIO()
        source.save(output, format="WEBP", quality=84, method=6)
        return ContentFile(output.getvalue(), name=f"{uuid4().hex}.webp")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Upload a valid JPEG, PNG, or WebP image.") from exc


@workspace_required("bookings")
def owner_dashboard(request):
    today = timezone.localdate()
    start, end = _selected_dates(request)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    bookings = Booking.objects.select_related("customer", "field").prefetch_related("payments")
    if query:
        bookings = bookings.filter(Q(reference__icontains=query) | Q(customer__name__icontains=query) | Q(customer__phone__icontains=query) | Q(team_name__icontains=query))
    if status in Booking.Status.values:
        bookings = bookings.filter(status=status)
    bookings = bookings.filter(play_date__gte=start, play_date__lte=end)
    daily = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        daily.append({
            "date": day,
            "bookings": Booking.objects.filter(play_date=day).exclude(status=Booking.Status.CANCELLED).count(),
            "revenue": PaymentRecord.objects.filter(booking__play_date=day, is_verified=True).exclude(kind=PaymentRecord.Kind.REFUND).aggregate(total=Sum("amount"))["total"] or 0,
        })
    peak_revenue = max((row["revenue"] for row in daily), default=0) or 1
    for row in daily:
        row["bar_height"] = max(8, round(row["revenue"] * 100 / peak_revenue))
    context = {
        "profile": TurfProfile.current(), "bookings": bookings.order_by("play_date", "start_time")[:100],
        "query": query, "selected_status": status, "booking_statuses": Booking.Status.choices,
        "today": today, "range_start": start, "range_end": end, "daily": daily,
        "today_count": Booking.objects.filter(play_date=today).exclude(status=Booking.Status.CANCELLED).count(),
        "today_revenue": PaymentRecord.objects.filter(booking__play_date=today, is_verified=True).exclude(kind=PaymentRecord.Kind.REFUND).aggregate(total=Sum("amount"))["total"] or 0,
        "month_revenue": PaymentRecord.objects.filter(received_at__date__gte=today.replace(day=1), received_at__date__lte=today, is_verified=True).exclude(kind=PaymentRecord.Kind.REFUND).aggregate(total=Sum("amount"))["total"] or 0,
        "pending_count": Booking.objects.filter(status=Booking.Status.PENDING).count(),
        "customer_count": Customer.objects.count(),
        "payment_verification_count": PaymentRecord.objects.filter(is_verified=False).count(),
        "fields": TurfField.objects.filter(is_active=True),
    }
    return render(request, "turf/owner_dashboard.html", context)


@workspace_required("bookings")
def booking_action(request, reference):
    if request.method != "POST":
        return redirect("owner_dashboard")
    booking = get_object_or_404(Booking, reference=reference)
    action = request.POST.get("action")
    if action in Booking.Status.values:
        booking.status = action
        if action == Booking.Status.CONFIRMED:
            booking.confirmed_by = request.user
        booking.save(update_fields=["status", "confirmed_by", "updated_at"])
        _audit(request, f"booking_{action}", booking, f"{booking.reference} marked {booking.get_status_display().lower()}.")
        messages.success(request, f"Booking {booking.reference} updated.")
    elif action in {"record_payment", "refund", "verify_payment"}:
        if request.workspace_member and not request.workspace_member.can_manage_payments:
            raise PermissionDenied
        if action == "verify_payment":
            payment = get_object_or_404(PaymentRecord, booking=booking, pk=request.POST.get("payment_id"), is_verified=False)
            payment.is_verified = True
            payment.received_by = request.user
            payment.save(update_fields=["is_verified", "received_by"])
            _sync_payment_status(booking)
            _audit(request, "payment_verified", booking, f"Payment verified for {booking.reference}.")
            messages.success(request, "Transaction marked verified.")
        else:
            try:
                amount = int(request.POST.get("amount", "0"))
                kind = PaymentRecord.Kind.REFUND if action == "refund" else PaymentRecord.Kind.PAYMENT
                paid = booking.paid_amount
                if amount <= 0 or (kind == PaymentRecord.Kind.REFUND and amount > paid):
                    raise ValueError
                payment = PaymentRecord.objects.create(
                    booking=booking, amount=amount, kind=kind,
                    method=request.POST.get("method", "cash")[:40],
                    transaction_reference=request.POST.get("transaction_reference", "").strip()[:100],
                    is_verified=True, received_by=request.user,
                    note=request.POST.get("note", "").strip()[:240],
                )
                _sync_payment_status(booking)
                _audit(request, f"payment_{kind}", payment, f"৳{amount} {kind} recorded for {booking.reference}.")
                messages.success(request, f"৳{amount:,} recorded.")
            except ValueError:
                messages.error(request, "Enter a valid amount. Refunds cannot exceed collected payments.")
    elif action == "reschedule":
        try:
            selected_start = datetime.fromisoformat(request.POST.get("start_at", ""))
            play_date, start_time = selected_start.date(), selected_start.time()
            field_obj = TurfField.objects.get(pk=request.POST.get("field", booking.field_id), is_active=True)
            count = int(request.POST.get("slot_count", "1"))
            with transaction.atomic():
                TurfField.objects.select_for_update().get(pk=field_obj.pk)
                quote = validate_booking_slot(TurfProfile.current(), play_date, start_time, count, field_obj, exclude_booking=booking)
                booking.field = field_obj
                booking.play_date = play_date
                booking.start_time, booking.end_time = quote["start"].time(), quote["end"].time()
                booking.end_day_offset = (quote["end"].date() - play_date).days
                booking.duration_minutes = quote["duration_minutes"]
                booking.total_amount, booking.price_snapshot = quote["price"], quote["price_snapshot"]
                booking.save()
            _audit(request, "booking_rescheduled", booking, f"{booking.reference} rescheduled to {play_date} {start_time}.")
            messages.success(request, "Booking rescheduled.")
        except (ValueError, ValidationError, TurfField.DoesNotExist) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, ValidationError) else "Choose a valid date, field and time.")
    return redirect("owner_dashboard")


def _sync_payment_status(booking):
    if booking.paid_amount >= booking.total_amount and booking.total_amount > 0:
        status = Booking.PaymentStatus.PAID
    elif booking.paid_amount > 0:
        status = Booking.PaymentStatus.PARTIAL
    elif booking.payments.filter(kind=PaymentRecord.Kind.REFUND, is_verified=True).exists():
        status = Booking.PaymentStatus.REFUNDED
    elif booking.payments.filter(is_verified=False).exists():
        status = Booking.PaymentStatus.PENDING_VERIFICATION
    else:
        status = Booking.PaymentStatus.UNPAID
    booking.payment_status = status
    booking.save(update_fields=["payment_status", "updated_at"])


@workspace_required("bookings")
def owner_manual_booking(request):
    profile = TurfProfile.current()
    fields = TurfField.objects.filter(is_active=True)
    if request.method == "POST":
        try:
            selected_start = datetime.fromisoformat(request.POST.get("start_at", ""))
            play_date, start_time = selected_start.date(), selected_start.time()
            field_obj = fields.get(pk=request.POST.get("field"))
            count = int(request.POST.get("slot_count", "1"))
            name, phone = request.POST.get("name", "").strip()[:100], request.POST.get("phone", "").strip()[:32]
            if not name or len(phone) < 7:
                raise ValidationError("Enter the player's name and mobile number.")
            with transaction.atomic():
                TurfField.objects.select_for_update().get(pk=field_obj.pk)
                quote = validate_booking_slot(profile, play_date, start_time, count, field_obj)
                payment_received = int(request.POST.get("payment_received", "0") or 0)
                if payment_received < 0 or payment_received > quote["price"]:
                    raise ValueError
                customer, _ = Customer.objects.get_or_create(phone=phone, defaults={"name": name})
                booking = Booking.objects.create(
                    customer=customer, field=field_obj, play_date=play_date,
                    start_time=quote["start"].time(), end_time=quote["end"].time(),
                    end_day_offset=(quote["end"].date() - play_date).days,
                    duration_minutes=quote["duration_minutes"], team_name=request.POST.get("team_name", "").strip()[:120],
                    players=int(request.POST.get("players", "0") or 0), total_amount=quote["price"],
                    advance_amount=payment_received,
                    status=Booking.Status.CONFIRMED, source=Booking.Source.MANUAL, created_by=request.user,
                    payment_method=request.POST.get("payment_method", Booking.PaymentMethod.TURF),
                    notes=request.POST.get("notes", "").strip()[:500], price_snapshot=quote["price_snapshot"],
                )
                initial_payment = payment_received
                if initial_payment:
                    PaymentRecord.objects.create(booking=booking, amount=initial_payment, kind=PaymentRecord.Kind.ADVANCE, method=request.POST.get("payment_method", "cash"), received_by=request.user)
                    _sync_payment_status(booking)
            _audit(request, "booking_created_manual", booking, f"Manual booking created for {booking.team_name or name}.")
            messages.success(request, f"Booking {booking.reference} added to the schedule.")
            return redirect("owner_dashboard")
        except (ValueError, ValidationError, TurfField.DoesNotExist) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, ValidationError) else "Check the player details and slot, then try again.")
    selected_date = request.GET.get("date", timezone.localdate().isoformat())
    field_obj = fields.filter(pk=request.GET.get("field", "")).first() or fields.first()
    try:
        slot_date = date.fromisoformat(selected_date)
    except ValueError:
        slot_date = timezone.localdate()
    return render(request, "turf/owner_manual_booking.html", {
        "profile": profile, "fields": fields, "selected_field": field_obj,
        "selected_date": slot_date, "selected_time": request.GET.get("time", ""),
        "slots": build_slots(profile, slot_date, field_obj),
        "minimum_slot_count": max(1, (field_obj.minimum_minutes + field_obj.slot_granularity_minutes - 1) // field_obj.slot_granularity_minutes) if field_obj else 1,
        "payment_methods": Booking.PaymentMethod.choices,
    })


@workspace_required("bookings")
def owner_availability(request):
    profile = TurfProfile.current()
    fields = TurfField.objects.filter(is_active=True)
    field_obj = fields.filter(pk=request.GET.get("field", request.POST.get("field", ""))).first() or fields.first()
    selected_date = timezone.localdate()
    if request.GET.get("date"):
        try:
            selected_date = date.fromisoformat(request.GET["date"])
        except ValueError:
            pass
    if request.method == "POST":
        try:
            closure_value = request.POST.get("closure_date", "")
            if closure_value:
                closure = SpecialClosure.objects.create(play_date=date.fromisoformat(closure_value), title=request.POST.get("closure_title", "").strip()[:120])
                _audit(request, "special_closure_added", closure, f"Closed the turf on {closure.play_date}.")
                messages.success(request, "Special closure added.")
                return redirect("owner_availability")
            block_date = date.fromisoformat(request.POST.get("play_date", ""))
            start_value, end_value = request.POST.get("start_time", ""), request.POST.get("end_time", "")
            start = datetime.strptime(start_value, "%H:%M").time() if start_value else None
            end = datetime.strptime(end_value, "%H:%M").time() if end_value else None
            if bool(start) != bool(end) or (start and start == end):
                raise ValueError
            end_day_offset = int(request.POST.get("end_day_offset", "0") or 0)
            if start and end and end < start:
                end_day_offset = 1
            block = BlockedSlot.objects.create(field=field_obj, play_date=block_date, start_time=start, end_time=end, end_day_offset=end_day_offset, reason=request.POST.get("reason", "").strip()[:140], created_by=request.user)
            _audit(request, "availability_blocked", block, f"Availability blocked on {block_date}.")
            messages.success(request, "Availability block added.")
            return redirect("owner_availability")
        except ValueError:
            messages.error(request, "Enter a valid date and both times, or leave both times blank for a full-day block.")
    days = []
    for offset in range(7):
        day = selected_date + timedelta(days=offset)
        slots = [slot for slot in build_slots(profile, day, field_obj) if slot["date"] == day]
        days.append({"date": day, "slots": slots, "open_count": sum(slot["available"] for slot in slots)})
    context = {
        "profile": profile, "fields": fields, "selected_field": field_obj, "selected_date": selected_date,
        "days": days, "blocks": BlockedSlot.objects.filter(play_date__gte=selected_date).order_by("play_date", "start_time"),
        "closures": SpecialClosure.objects.filter(play_date__gte=selected_date).order_by("play_date"),
    }
    return render(request, "turf/owner_availability.html", context)


@workspace_required("bookings")
def owner_unblock(request, block_id):
    if request.method == "POST":
        block = get_object_or_404(BlockedSlot, pk=block_id)
        _audit(request, "availability_unblocked", block, "An availability block was removed.")
        block.delete()
        messages.success(request, "Availability block removed.")
    return redirect("owner_availability")


@workspace_required("bookings")
def owner_remove_closure(request, closure_id):
    if request.method == "POST":
        closure = get_object_or_404(SpecialClosure, pk=closure_id)
        _audit(request, "special_closure_removed", closure, f"Reopened the turf on {closure.play_date}.")
        closure.delete()
        messages.success(request, "Closure removed.")
    return redirect("owner_availability")


@workspace_required("settings")
def owner_settings(request):
    profile = TurfProfile.current()
    if request.method == "POST":
        try:
            weekday = int(request.POST.get("weekday_rate", "0"))
            weekend = int(request.POST.get("weekend_rate", "0"))
            advance = int(request.POST.get("advance_percent", "30"))
            if min(weekday, weekend) < 0 or not 0 <= advance <= 100:
                raise ValueError
            profile.name = request.POST.get("name", "").strip()[:120] or profile.name
            profile.tagline = request.POST.get("tagline", "").strip()[:180]
            profile.address = request.POST.get("address", "").strip()[:240]
            profile.phone = request.POST.get("phone", "").strip()[:32]
            profile.whatsapp = request.POST.get("whatsapp", "").strip()[:32]
            profile.email = request.POST.get("email", "").strip()[:254]
            profile.maps_url = request.POST.get("maps_url", "").strip()
            profile.latitude = request.POST.get("latitude") or None
            profile.longitude = request.POST.get("longitude") or None
            profile.booking_instructions = request.POST.get("booking_instructions", "").strip()
            profile.cancellation_policy = request.POST.get("cancellation_policy", "").strip()
            profile.payment_details = request.POST.get("payment_details", "").strip()
            profile.public_booking_enabled = request.POST.get("public_booking_enabled") == "on"
            profile.weekday_rate, profile.weekend_rate, profile.advance_percent = weekday, weekend, advance
            theme_color = request.POST.get("theme_color", profile.theme_color)
            if re.fullmatch(r"#[0-9a-fA-F]{6}", theme_color):
                profile.theme_color = theme_color
            if request.FILES.get("profile_picture"):
                profile.profile_picture.save("profile.webp", _safe_webp_upload(request.FILES["profile_picture"]), save=False)
            profile.save()
            _audit(request, "turf_settings_updated", profile, "Turf public profile and settings updated.")
            messages.success(request, "Turf settings saved.")
            return redirect("owner_settings")
        except (ValueError, TypeError):
            messages.error(request, "Check rates, map coordinates and deposit percentage, then try again.")
    return render(request, "turf/owner_settings.html", {"profile": profile, "fields": TurfField.objects.all(), "hours": OperatingHours.objects.all(), "rules": PricingRule.objects.select_related("field").all()})


@workspace_required("settings")
def owner_fields(request):
    if request.method == "POST":
        field_id = request.POST.get("field_id")
        field_obj = get_object_or_404(TurfField, pk=field_id) if field_id else TurfField()
        field_obj.name = request.POST.get("name", "").strip()[:100]
        field_obj.description = request.POST.get("description", "").strip()[:240]
        field_obj.size = request.POST.get("size", "").strip()[:40]
        field_obj.surface = request.POST.get("surface", "").strip()[:60]
        field_obj.is_indoor = request.POST.get("is_indoor") == "on"
        field_obj.has_lighting = request.POST.get("has_lighting") == "on"
        field_obj.slot_granularity_minutes = int(request.POST.get("slot_granularity_minutes", "30"))
        field_obj.minimum_minutes = int(request.POST.get("minimum_minutes", "60"))
        field_obj.is_active = request.POST.get("is_active") == "on"
        if field_obj.name and field_obj.slot_granularity_minutes > 0 and field_obj.minimum_minutes > 0:
            field_obj.save()
            _audit(request, "field_saved", field_obj, f"Field {field_obj.name} saved.")
            messages.success(request, "Field saved.")
        else:
            messages.error(request, "Enter a name and valid slot lengths.")
        return redirect("owner_fields")
    return render(request, "turf/owner_fields.html", {"profile": TurfProfile.current(), "fields": TurfField.objects.all()})


@workspace_required("settings")
def owner_hours(request):
    if request.method == "POST":
        try:
            weekday = int(request.POST.get("weekday", "0"))
            profile = TurfProfile.current()
            hours = OperatingHours.objects.get_or_create(weekday=weekday, defaults={
                "opens_at": profile.opening_time, "closes_at": profile.closing_time,
                "closes_next_day": profile.closes_next_day,
            })[0]
            hours.is_closed = request.POST.get("is_closed") == "on"
            if not hours.is_closed:
                hours.opens_at = datetime.strptime(request.POST.get("opens_at", ""), "%H:%M").time()
                hours.closes_at = datetime.strptime(request.POST.get("closes_at", ""), "%H:%M").time()
                hours.closes_next_day = request.POST.get("closes_next_day") == "on"
                if (hours.closes_next_day and hours.closes_at >= hours.opens_at) or (not hours.closes_next_day and hours.closes_at <= hours.opens_at):
                    raise ValueError
            hours.save()
            _audit(request, "hours_saved", hours, f"Opening hours updated for {hours.get_weekday_display()}.")
            messages.success(request, "Opening hours saved.")
        except (ValueError, OperatingHours.DoesNotExist):
            messages.error(request, "Choose valid opening hours.")
    profile = TurfProfile.current()
    saved = {row.weekday: row for row in OperatingHours.objects.all()}
    day_rows = [{
        "weekday": value, "label": label, "hours": saved.get(value),
        "opens_at": saved[value].opens_at if value in saved else profile.opening_time,
        "closes_at": saved[value].closes_at if value in saved else profile.closing_time,
        "closes_next_day": saved[value].closes_next_day if value in saved else profile.closes_next_day,
        "is_closed": saved[value].is_closed if value in saved else False,
    } for value, label in OperatingHours.WEEKDAYS]
    return render(request, "turf/owner_hours.html", {"profile": profile, "day_rows": day_rows})


@workspace_required("settings")
def owner_pricing(request):
    if request.method == "POST":
        if request.POST.get("delete_id"):
            rule = get_object_or_404(PricingRule, pk=request.POST["delete_id"])
            _audit(request, "pricing_rule_removed", rule, f"Pricing rule {rule.label} removed.")
            rule.delete()
            messages.success(request, "Pricing rule removed.")
            return redirect("owner_pricing")
        try:
            rule_id = request.POST.get("rule_id")
            rule = get_object_or_404(PricingRule, pk=rule_id) if rule_id else PricingRule()
            rule.kind = request.POST.get("kind", PricingRule.Kind.WEEKDAY)
            rule.label = request.POST.get("label", "").strip()[:80]
            rule.hourly_rate = int(request.POST.get("hourly_rate", "0"))
            rule.priority = int(request.POST.get("priority", "10"))
            field_id = request.POST.get("field")
            rule.field = TurfField.objects.filter(pk=field_id).first() if field_id else None
            date_value = request.POST.get("play_date", "")
            rule.play_date = date.fromisoformat(date_value) if date_value else None
            rule.weekdays = [int(v) for v in request.POST.getlist("weekdays")]
            starts, ends = request.POST.get("starts_at", ""), request.POST.get("ends_at", "")
            rule.starts_at = datetime.strptime(starts, "%H:%M").time() if starts else None
            rule.ends_at = datetime.strptime(ends, "%H:%M").time() if ends else None
            rule.is_active = request.POST.get("is_active") == "on"
            if rule.hourly_rate < 0 or not rule.label:
                raise ValueError
            rule.save()
            _audit(request, "pricing_rule_saved", rule, f"Pricing rule {rule.label} saved.")
            messages.success(request, "Pricing rule saved.")
        except ValueError:
            messages.error(request, "Check the date, time band and rate.")
        return redirect("owner_pricing")
    return render(request, "turf/owner_pricing.html", {"profile": TurfProfile.current(), "rules": PricingRule.objects.select_related("field"), "fields": TurfField.objects.all(), "kinds": PricingRule.Kind.choices, "weekdays": OperatingHours.WEEKDAYS})


@workspace_required("settings")
def owner_gallery(request):
    if request.method == "POST":
        if request.POST.get("delete_id"):
            photo = get_object_or_404(GalleryPhoto, pk=request.POST["delete_id"])
            photo.image.delete(save=False)
            photo.delete()
            messages.success(request, "Photo removed.")
        else:
            image = request.FILES.get("image")
            if GalleryPhoto.objects.count() >= 12:
                messages.error(request, "The public gallery can contain up to 12 photos.")
            else:
                try:
                    safe_image = _safe_webp_upload(image)
                    photo = GalleryPhoto.objects.create(image=safe_image, caption=request.POST.get("caption", "").strip()[:120])
                    _audit(request, "gallery_photo_added", photo, "A public gallery photo was added.")
                    messages.success(request, "Photo added to the public page.")
                except ValueError as exc:
                    messages.error(request, str(exc))
        return redirect("owner_gallery")
    return render(request, "turf/owner_gallery.html", {"profile": TurfProfile.current(), "photos": GalleryPhoto.objects.all(), "photo_count": GalleryPhoto.objects.count()})


@workspace_required("payments")
def owner_expenses(request):
    if request.method == "POST":
        try:
            expense = Expense.objects.create(
                date=date.fromisoformat(request.POST.get("date", "")),
                category=request.POST.get("category", Expense.Category.OTHER),
                description=request.POST.get("description", "").strip()[:180],
                amount=int(request.POST.get("amount", "0")),
                receipt_reference=request.POST.get("receipt_reference", "").strip()[:100],
                created_by=request.user,
            )
            if expense.amount <= 0 or not expense.description:
                expense.delete()
                raise ValueError
            _audit(request, "expense_created", expense, f"৳{expense.amount} expense recorded.")
            messages.success(request, "Expense saved.")
            return redirect("owner_expenses")
        except (ValueError, TypeError):
            messages.error(request, "Enter a date, description and amount greater than zero.")
    expenses = Expense.objects.all()
    expense_total = expenses.filter(date__month=timezone.localdate().month, date__year=timezone.localdate().year).aggregate(total=Sum("amount"))["total"] or 0
    return render(request, "turf/owner_expenses.html", {"profile": TurfProfile.current(), "expenses": expenses[:100], "expense_total": expense_total, "categories": Expense.Category.choices})


@workspace_required("payments")
def owner_reports(request):
    start, end = _selected_dates(request)
    bookings = Booking.objects.filter(play_date__gte=start, play_date__lte=end)
    payments = PaymentRecord.objects.filter(booking__play_date__gte=start, booking__play_date__lte=end, is_verified=True)
    revenue = payments.exclude(kind=PaymentRecord.Kind.REFUND).aggregate(total=Sum("amount"))["total"] or 0
    refunds = payments.filter(kind=PaymentRecord.Kind.REFUND).aggregate(total=Sum("amount"))["total"] or 0
    expenses = Expense.objects.filter(date__gte=start, date__lte=end).aggregate(total=Sum("amount"))["total"] or 0
    daily = []
    day = start
    while day <= end and len(daily) < 62:
        day_bookings = bookings.filter(play_date=day)
        day_revenue = payments.filter(booking__play_date=day).exclude(kind=PaymentRecord.Kind.REFUND).aggregate(total=Sum("amount"))["total"] or 0
        daily.append({"date": day, "count": day_bookings.exclude(status=Booking.Status.CANCELLED).count(), "revenue": day_revenue})
        day += timedelta(days=1)
    return render(request, "turf/owner_reports.html", {
        "profile": TurfProfile.current(), "range_start": start, "range_end": end,
        "booking_count": bookings.exclude(status=Booking.Status.CANCELLED).count(),
        "confirmed_count": bookings.filter(status=Booking.Status.CONFIRMED).count(),
        "revenue": revenue, "refunds": refunds, "expenses": expenses,
        "net": revenue - refunds - expenses, "due": sum(b.amount_due for b in bookings.prefetch_related("payments")), "daily": daily,
    })


@workspace_required("payments")
def owner_export(request):
    start, end = _selected_dates(request)
    bookings = Booking.objects.filter(play_date__gte=start, play_date__lte=end).select_related("customer", "field").prefetch_related("payments")
    if request.GET.get("format") == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Bookings"
        sheet.append(["Reference", "Date", "Start", "End", "Field", "Team", "Customer", "Phone", "Total BDT", "Paid BDT", "Due BDT", "Booking status", "Payment status"])
        for booking in bookings:
            sheet.append([booking.reference, booking.play_date.isoformat(), booking.start_time.strftime("%H:%M"), booking.end_time.strftime("%H:%M"), str(booking.field or ""), booking.team_name, booking.customer.name, booking.customer.phone, booking.total_amount, booking.paid_amount, booking.amount_due, booking.status, booking.payment_status])
        output = BytesIO()
        workbook.save(output)
        response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = "attachment; filename=dipu-turf-bookings.xlsx"
        return response
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = "attachment; filename=dipu-turf-bookings.csv"
    writer = csv.writer(response)
    writer.writerow(["Reference", "Date", "Start", "End", "Field", "Team", "Customer", "Phone", "Total BDT", "Paid BDT", "Due BDT", "Booking status", "Payment status"])
    for booking in bookings:
        writer.writerow([booking.reference, booking.play_date, booking.start_time, booking.end_time, booking.field or "", booking.team_name, booking.customer.name, booking.customer.phone, booking.total_amount, booking.paid_amount, booking.amount_due, booking.status, booking.payment_status])
    return response


@workspace_required("bookings")
def owner_customers(request):
    query = request.GET.get("q", "").strip()
    if request.method == "POST":
        customer = get_object_or_404(Customer, pk=request.POST.get("customer_id"))
        customer.email = request.POST.get("email", "").strip()[:254]
        customer.notes = request.POST.get("notes", "").strip()[:2000]
        customer.save(update_fields=["email", "notes", "updated_at"])
        _audit(request, "customer_updated", customer, f"Player record updated for {customer.name}.")
        messages.success(request, "Player record saved.")
        return redirect("owner_customers")
    customers = Customer.objects.annotate(
        booking_count=Count("bookings", distinct=True),
        spent=Sum(Case(
            When(bookings__payments__is_verified=True, bookings__payments__kind=PaymentRecord.Kind.REFUND, then=-F("bookings__payments__amount")),
            When(bookings__payments__is_verified=True, then=F("bookings__payments__amount")),
            default=0, output_field=IntegerField(),
        )),
    )
    if query:
        customers = customers.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query))
    return render(request, "turf/owner_customers.html", {"profile": TurfProfile.current(), "customers": customers.order_by("-created_at"), "query": query})


@workspace_required("settings")
def owner_managers(request):
    if not (request.user.is_superuser or request.user.is_staff):
        raise PermissionDenied
    if request.method == "POST":
        if request.POST.get("remove_id"):
            member = get_object_or_404(WorkspaceMember, pk=request.POST["remove_id"])
            member.is_active = False
            member.save(update_fields=["is_active"])
            messages.success(request, "Workspace access removed.")
        else:
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")
            if not username or len(password) < 10 or User.objects.filter(username=username).exists():
                messages.error(request, "Choose an unused username and a password with at least 10 characters.")
            else:
                user = User.objects.create_user(username=username, password=password, first_name=request.POST.get("name", "").strip()[:100])
                WorkspaceMember.objects.create(user=user, role=request.POST.get("role", "manager"))
                _audit(request, "workspace_member_added", user, f"Workspace access added for {username}.")
                messages.success(request, f"{username} can now sign in as a manager.")
        return redirect("owner_managers")
    return render(request, "turf/owner_managers.html", {"profile": TurfProfile.current(), "members": WorkspaceMember.objects.select_related("user").all()})


@workspace_required("settings")
def owner_qr(request):
    from django.urls import reverse
    import segno
    from django.http import HttpResponseRedirect
    qr_obj = BookingQRCode.objects.filter(is_active=True).first()
    if not qr_obj:
        qr_obj = BookingQRCode.objects.create(created_by=request.user)
        _audit(request, "booking_qr_created", qr_obj, "Public booking QR code created.")
    booking_url = request.build_absolute_uri(reverse("public_qr", args=[qr_obj.token]))
    if request.method == "POST" and request.POST.get("revoke"):
        qr_obj.is_active = False
        qr_obj.revoked_at = timezone.now()
        qr_obj.save(update_fields=["is_active", "revoked_at"])
        messages.success(request, "Old QR code revoked. A new code is ready.")
        return HttpResponseRedirect(reverse("owner_qr"))
    output = BytesIO()
    segno.make(booking_url, error="m").save(output, kind="svg", scale=8, border=2, dark="#183523", light="#ffffff")
    response = render(request, "turf/owner_qr.html", {"profile": TurfProfile.current(), "booking_url": booking_url, "qr_svg": output.getvalue().decode("utf-8")})
    return response


@workspace_required()
def owner_activity(request):
    return render(request, "turf/owner_activity.html", {"profile": TurfProfile.current(), "events": ActivityLog.objects.select_related("actor")[:150]})


@workspace_required()
def owner_account(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, request.user)
            _audit(request, "password_changed", request.user, "Workspace password changed.")
            messages.success(request, "Password changed.")
            return redirect("owner_account")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, "turf/owner_account.html", {"profile": TurfProfile.current(), "form": form})
