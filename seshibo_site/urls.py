from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('home.urls')),   # 👈 include ALL urls from the home apppath('portal/staff/', include('staff_portal.urls')),
    path('portal/staff/', include('staff_portal.urls')),
    path("portal/staff/suppliers/", include("suppliers.urls")),
    path("portal/staff/products/", include("products.urls")),
    path("portal/staff/clients/", include("clients.urls")),
    path("portal/staff/orders/", include("orders.urls")),
    path("portal/staff/invoices/", include("invoices.urls")),
    path("portal/staff/deliveries/", include("deliveries.urls")),
    path("portal/staff/transactions/", include("transactions.urls")),
    path("portal/staff/credit/", include("credit.urls")),
    path("portal/staff/tasks/", include("tasks.urls")),
    path("portal/staff/lender/", include("lender.urls")),
    path("portal/staff/sales/", include("sales.urls")),
    path("portal/staff/logistics/", include("logistics.urls")),
    path("portal/staff/payments/", include("payments.urls")),
    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)