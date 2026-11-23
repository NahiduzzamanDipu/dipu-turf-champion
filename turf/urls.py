from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("book/", views.book, name="book"),
    path("booking/lookup/", views.booking_lookup, name="booking_lookup"),
    path("owner/login/", views.owner_login, name="owner_login"),
    path("owner/logout/", views.owner_logout, name="owner_logout"),
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
    path("owner/booking/<str:reference>/", views.booking_action, name="booking_action"),
    path("owner/settings/", views.owner_settings, name="owner_settings"),
    path("owner/availability/", views.owner_availability, name="owner_availability"),
    path("owner/availability/<int:block_id>/remove/", views.owner_unblock, name="owner_unblock"),
    path("owner/export/", views.owner_export, name="owner_export"),
]
