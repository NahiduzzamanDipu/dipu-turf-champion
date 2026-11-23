from django.contrib import admin
from .models import BlockedSlot, Booking, Customer, PaymentRecord, TurfProfile


class PaymentInline(admin.TabularInline):
    model = PaymentRecord
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "play_date", "start_time", "total_amount", "status", "payment_status")
    list_filter = ("status", "payment_status", "play_date")
    search_fields = ("reference", "customer__name", "customer__phone")
    inlines = (PaymentInline,)


@admin.register(TurfProfile)
class TurfProfileAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not TurfProfile.objects.exists()


admin.site.register(Customer)
admin.site.register(BlockedSlot)
