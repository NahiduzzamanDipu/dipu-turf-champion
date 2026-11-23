import csv
from datetime import date, datetime, timedelta
from io import StringIO

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import BlockedSlot, Booking, Customer, PaymentRecord, TurfProfile, build_slots, validate_booking_slot


def home(request):
    profile = TurfProfile.current()
    selected_date = timezone.localdate() + timedelta(days=1)
    slots = build_slots(profile, selected_date)
    return render(request, "turf/home.html", {"profile": profile, "featured_slots": [s for s in slots if s["available"]][:4]})


def book(request):
    profile = TurfProfile.current()
    default_date = timezone.localdate() + timedelta(days=1)
    try:
        selected_date = date.fromisoformat(request.GET.get("date", "")) if request.GET.get("date") else default_date
    except ValueError:
        selected_date = default_date
    selected_date = max(selected_date, timezone.localdate())
    slots = build_slots(profile, selected_date)
    if request.method == "POST":
        try:
            play_date = date.fromisoformat(request.POST.get("play_date", ""))
            if play_date < timezone.localdate():
                raise ValidationError("Choose today or a future date for your game.")
            start = datetime.strptime(request.POST.get("start_time", ""), "%H:%M").time()
            name = request.POST.get("name", "").strip()[:100]
            phone = request.POST.get("phone", "").strip()[:32]
            method = request.POST.get("payment_method", Booking.PaymentMethod.TURF)
            if not name or len(phone) < 7:
                raise ValidationError("Add your name and a valid mobile number.")
            if method not in Booking.PaymentMethod.values:
                raise ValidationError("Choose a payment method.")
            with transaction.atomic():
                profile = TurfProfile.objects.select_for_update().get(pk=1)
                slot = validate_booking_slot(profile, play_date, start)
                customer, _ = Customer.objects.get_or_create(phone=phone, defaults={"name": name})
                if customer.name != name:
                    customer.name = name
                    customer.save(update_fields=["name"])
                advance = round(slot["price"] * profile.advance_percent / 100)
                booking = Booking.objects.create(
                    customer=customer, play_date=play_date, start_time=start, end_time=slot["end"],
                    total_amount=slot["price"], advance_amount=advance, payment_method=method,
                    notes=request.POST.get("notes", "").strip()[:500],
                )
            return render(request, "turf/booking_success.html", {"profile": profile, "booking": booking})
        except (ValueError, ValidationError, TurfProfile.DoesNotExist) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, ValidationError) else "Choose a valid date and time.")
            selected_date = timezone.localdate() + timedelta(days=1)
            slots = build_slots(profile, selected_date)
    return render(request, "turf/book.html", {"profile": profile, "selected_date": selected_date, "slots": slots, "min_date": timezone.localdate().isoformat()})


def booking_lookup(request):
    profile = TurfProfile.current()
    booking = None
    searched = False
    if request.method == "POST":
        searched = True
        booking = Booking.objects.filter(
            reference__iexact=request.POST.get("reference", "").strip(),
            customer__phone=request.POST.get("phone", "").strip(),
        ).select_related("customer").first()
        if not booking:
            messages.error(request, "We could not find a booking with those details.")
    return render(request, "turf/lookup.html", {"profile": profile, "booking": booking, "searched": searched})


def owner_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("owner_dashboard")
    if request.method == "POST":
        user = authenticate(request, username=request.POST.get("username", ""), password=request.POST.get("password", ""))
        if user and user.is_staff:
            login(request, user)
            return redirect("owner_dashboard")
        messages.error(request, "Those sign-in details did not match an owner account.")
    return render(request, "turf/owner_login.html", {"profile": TurfProfile.current()})


def owner_logout(request):
    if request.method == "POST":
        logout(request)
    return redirect("home")


@login_required
def owner_dashboard(request):
    if not request.user.is_staff:
        return redirect("owner_login")
    today = timezone.localdate()
    month_start = today.replace(day=1)
    bookings = Booking.objects.select_related("customer").prefetch_related("payments").all()
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        from django.db.models import Q
        bookings = bookings.filter(Q(reference__icontains=query) | Q(customer__name__icontains=query) | Q(customer__phone__icontains=query))
    if status in Booking.Status.values:
        bookings = bookings.filter(status=status)
    totals = Booking.objects.filter(play_date=today).aggregate(count=Count("id", distinct=True), revenue=Sum("payments__amount"))
    month_revenue = PaymentRecord.objects.filter(received_at__date__gte=month_start, received_at__date__lte=today).aggregate(total=Sum("amount"))["total"] or 0
    context = {
        "profile": TurfProfile.current(), "bookings": bookings.order_by("-created_at")[:60], "query": query,
        "selected_status": status, "today_count": totals["count"] or 0, "today_revenue": totals["revenue"] or 0,
        "month_revenue": month_revenue, "pending_count": Booking.objects.filter(status=Booking.Status.PENDING).count(),
        "customer_count": Customer.objects.count(), "today": today, "booking_statuses": Booking.Status.choices,
    }
    return render(request, "turf/owner_dashboard.html", context)


@login_required
def booking_action(request, reference):
    if not request.user.is_staff:
        return redirect("owner_login")
    if request.method == "POST":
        booking = get_object_or_404(Booking, reference=reference)
        action = request.POST.get("action")
        if action in Booking.Status.values:
            booking.status = action
            booking.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Booking {booking.reference} marked {booking.get_status_display().lower()}.")
        elif action == "record_payment":
            try:
                amount = int(request.POST.get("amount", "0"))
                tx_ref = request.POST.get("transaction_reference", "").strip()[:100]
                if amount <= 0:
                    raise ValueError
                PaymentRecord.objects.create(booking=booking, amount=amount, method=request.POST.get("method", "cash"), transaction_reference=tx_ref, received_by=request.user)
                received = booking.payments.aggregate(total=Sum("amount"))["total"] or 0
                booking.payment_status = Booking.PaymentStatus.PAID if received >= booking.total_amount else Booking.PaymentStatus.PARTIAL
                booking.transaction_reference = tx_ref
                booking.save(update_fields=["payment_status", "transaction_reference", "updated_at"])
                messages.success(request, f"Payment of ৳{amount:,} recorded for {booking.reference}.")
            except ValueError:
                messages.error(request, "Enter a payment amount greater than zero.")
    return redirect("owner_dashboard")


@login_required
def owner_settings(request):
    if not request.user.is_staff:
        return redirect("owner_login")
    profile = TurfProfile.current()
    if request.method == "POST":
        try:
            opening = datetime.strptime(request.POST.get("opening_time", ""), "%H:%M").time()
            closing = datetime.strptime(request.POST.get("closing_time", ""), "%H:%M").time()
            weekday = int(request.POST.get("weekday_rate", "0"))
            weekend = int(request.POST.get("weekend_rate", "0"))
            advance = int(request.POST.get("advance_percent", "30"))
            if opening >= closing or min(weekday, weekend) < 0 or not 0 <= advance <= 100:
                raise ValueError
            profile.name = request.POST.get("name", "").strip()[:120] or profile.name
            profile.tagline = request.POST.get("tagline", "").strip()[:180]
            profile.address = request.POST.get("address", "").strip()[:240]
            profile.phone = request.POST.get("phone", "").strip()[:32]
            profile.whatsapp = request.POST.get("whatsapp", "").strip()[:32]
            profile.email = request.POST.get("email", "").strip()[:254]
            profile.maps_url = request.POST.get("maps_url", "").strip()
            profile.opening_time, profile.closing_time = opening, closing
            profile.weekday_rate, profile.weekend_rate, profile.advance_percent = weekday, weekend, advance
            profile.save()
            messages.success(request, "Turf settings saved.")
            return redirect("owner_settings")
        except ValueError:
            messages.error(request, "Check the hours, rates and deposit percentage, then try again.")
    return render(request, "turf/owner_settings.html", {"profile": profile})


@login_required
def owner_availability(request):
    if not request.user.is_staff:
        return redirect("owner_login")
    profile = TurfProfile.current()
    if request.method == "POST":
        try:
            block_date = date.fromisoformat(request.POST.get("play_date", ""))
            start_value, end_value = request.POST.get("start_time", ""), request.POST.get("end_time", "")
            start = datetime.strptime(start_value, "%H:%M").time() if start_value else None
            end = datetime.strptime(end_value, "%H:%M").time() if end_value else None
            if bool(start) != bool(end) or (start and start >= end):
                raise ValueError
            BlockedSlot.objects.create(play_date=block_date, start_time=start, end_time=end, reason=request.POST.get("reason", "").strip()[:140], created_by=request.user)
            messages.success(request, "Availability block added.")
            return redirect("owner_availability")
        except ValueError:
            messages.error(request, "Enter a valid date and both times, or leave both times blank for a full-day block.")
    today = timezone.localdate()
    days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        slots = build_slots(profile, day)
        days.append({"date": day, "slots": slots, "open_count": sum(slot["available"] for slot in slots)})
    return render(request, "turf/owner_availability.html", {"profile": profile, "days": days, "blocks": BlockedSlot.objects.filter(play_date__gte=today).order_by("play_date", "start_time")})


@login_required
def owner_unblock(request, block_id):
    if not request.user.is_staff:
        return redirect("owner_login")
    if request.method == "POST":
        block = get_object_or_404(BlockedSlot, pk=block_id)
        block.delete()
        messages.success(request, "Availability block removed.")
    return redirect("owner_availability")


@login_required
def owner_export(request):
    if not request.user.is_staff:
        return redirect("owner_login")
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Reference", "Date", "Start", "End", "Customer", "Phone", "Total BDT", "Paid BDT", "Booking status", "Payment status"])
    for booking in Booking.objects.select_related("customer").all():
        paid = booking.payments.aggregate(total=Sum("amount"))["total"] or 0
        writer.writerow([booking.reference, booking.play_date, booking.start_time, booking.end_time, booking.customer.name, booking.customer.phone, booking.total_amount, paid, booking.status, booking.payment_status])
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = "attachment; filename=dipu-turf-bookings.csv"
    return response
