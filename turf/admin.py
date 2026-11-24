from django.contrib import admin

from .models import (
    ActivityLog, BlockedSlot, Booking, BookingQRCode, Customer, Expense,
    GalleryPhoto, OperatingHours, PaymentRecord, PricingRule, SpecialClosure,
    TurfField, TurfProfile, WorkspaceMember,
)


class PaymentInline(admin.TabularInline):
    model = PaymentRecord
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "play_date", "start_time", "field", "total_amount", "status", "payment_status")
    list_filter = ("status", "payment_status", "play_date", "field")
    search_fields = ("reference", "customer__name", "customer__phone", "team_name")
    inlines = (PaymentInline,)


@admin.register(TurfProfile)
class TurfProfileAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not TurfProfile.objects.exists()


@admin.register(PricingRule)
class PricingRuleAdmin(admin.ModelAdmin):
    list_display = ("label", "kind", "field", "hourly_rate", "priority", "is_active")
    list_filter = ("kind", "is_active", "field")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "description", "amount", "created_by")
    list_filter = ("category", "date")
    search_fields = ("description", "receipt_reference")


admin.site.register([Customer, BlockedSlot, TurfField, OperatingHours, SpecialClosure, GalleryPhoto, WorkspaceMember, BookingQRCode, ActivityLog])
