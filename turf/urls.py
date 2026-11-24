from django.urls import path
from . import views
from . import workspace

urlpatterns = [
    path("", views.home, name="home"),
    path("book/", views.book, name="book"),
    path("booking/lookup/", views.booking_lookup, name="booking_lookup"),
    path("owner/login/", views.owner_login, name="owner_login"),
    path("owner/logout/", views.owner_logout, name="owner_logout"),
    path("owner/", workspace.owner_dashboard, name="owner_dashboard"),
    path("owner/booking/add/", workspace.owner_manual_booking, name="owner_manual_booking"),
    path("owner/booking/<str:reference>/", workspace.booking_action, name="booking_action"),
    path("owner/settings/", workspace.owner_settings, name="owner_settings"),
    path("owner/fields/", workspace.owner_fields, name="owner_fields"),
    path("owner/hours/", workspace.owner_hours, name="owner_hours"),
    path("owner/pricing/", workspace.owner_pricing, name="owner_pricing"),
    path("owner/gallery/", workspace.owner_gallery, name="owner_gallery"),
    path("owner/availability/", workspace.owner_availability, name="owner_availability"),
    path("owner/availability/<int:block_id>/remove/", workspace.owner_unblock, name="owner_unblock"),
    path("owner/availability/closure/<int:closure_id>/remove/", workspace.owner_remove_closure, name="owner_remove_closure"),
    path("owner/expenses/", workspace.owner_expenses, name="owner_expenses"),
    path("owner/reports/", workspace.owner_reports, name="owner_reports"),
    path("owner/export/", workspace.owner_export, name="owner_export"),
    path("owner/customers/", workspace.owner_customers, name="owner_customers"),
    path("owner/team/", workspace.owner_managers, name="owner_managers"),
    path("owner/qr/", workspace.owner_qr, name="owner_qr"),
    path("owner/activity/", workspace.owner_activity, name="owner_activity"),
    path("owner/account/", workspace.owner_account, name="owner_account"),
    path("b/<str:token>/", views.public_qr, name="public_qr"),
]
