from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("turf.urls")),
    path("service-worker.js", TemplateView.as_view(template_name="turf/service_worker.js", content_type="application/javascript"), name="service_worker"),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
