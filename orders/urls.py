from django.urls import path
from . import views


urlpatterns = [
    path("", views.order_list, name="staff-orders"),
    path("new/", views.order_create, name="order-create"),
    path("<int:pk>/edit/", views.order_edit, name="order-edit"),
    path("<int:pk>/view/", views.order_view, name="order-view"),
    path("orders/<int:pk>/delete/", views.order_delete, name="order-delete"),
    path("ajax/products-by-category/", views.ajax_products_by_category, name="ajax-products-by-category"),
    path("delivery-note/<int:stop_id>/",views.delivery_note_view,name="delivery-note-view"),
    path("delivery-note/<int:stop_id>/email/",views.send_delivery_note_email,name="delivery-note-email",),
    path("quotations/", views.quotation_list, name="staff-quotations"), 
    path("quotations/new/", views.quotation_create, name="quotation-create"),
    path("quotations/<int:pk>/view/", views.quotation_view, name="quotation-view"),
    path("quotations/<int:pk>/edit/", views.quotation_edit, name="quotation-edit"),
    path("q/<uuid:token>/", views.public_quotation_view, name="public_quotation_view",),
    path("quotations/<int:pk>/send-whatsapp/", views.send_quotation_whatsapp_view, name="send-quotation-whatsapp",),
    path("orders/q/<uuid:token>/accept/", views.public_accept_quotation_view, name="public-quotation-accept",),
    path("orders/q/<uuid:token>/reject/", views.public_reject_quotation_view, name="public-quotation-reject",),
    path("quotations/<int:pk>/send-sms/", views.send_quotation_sms, name="send-quotation-sms",),
    path("quotations/<int:pk>/send-email/", views.send_quotation_email_internal, name="send-quotation-email",),
    path("dashboard/", views.staff_sales_dashboard, name="staff-sales-dashboard"),
    
]
