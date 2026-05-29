from django.urls import path
from . import views

app_name = "sales"

urlpatterns = [
    # Main sales dashboard
    path("", views.sales_dashboard, name="sales-dashboard"),

    # Prospects
    path("prospects/", views.prospects, name="sales-prospects"),
    path("prospects/add/", views.prospect_create, name="sales-prospect-create"),
    path("prospects/<int:pk>/", views.prospect_detail, name="sales-prospect-detail"),
    path(
        "prospects/<int:pk>/add-update/",
        views.prospect_update_create,
        name="sales-prospect-add-update",
    ),
    path(
        "prospects/<int:pk>/stage-action/",
        views.prospect_stage_action,
        name="sales-prospect-stage-action",
    ),
    path(
        "prospects/<int:pk>/edit/",
        views.prospect_edit,
        name="sales-prospect-edit",
    ),
    # Stage action buttons (pass / lost etc.)
    path(
        "prospects/<int:pk>/stage-action/",
        views.prospect_stage_action,
        name="sales-prospect-stage-action",
    ),

    # Re-open closed prospect
    path(
        "prospects/<int:pk>/reopen/",
        views.prospect_reopen,
        name="sales-prospect-reopen",
    ),


    # NEW: logging endpoints for each stage tab
    path(
        "prospects/<int:pk>/contact-log/",
        views.prospect_contact_log,
        name="sales-prospect-contact-log",
    ),
    path(
        "prospects/<int:pk>/site-visit-log/",
        views.prospect_site_visit_log,
        name="sales-prospect-site-visit-log",
    ),
    path(
        "prospects/<int:pk>/negotiation-log/",
        views.prospect_negotiation_log,
        name="sales-prospect-negotiation-log",
    ),

    # Clients (sales view over existing clients)
    path("clients/", views.clients, name="sales-clients"),
    path("clients/<int:pk>/edit/", views.edit_client, name="edit-client"),
    path("clients/<int:pk>/view/", views.view_client, name="client-detail"),


    path("quotations/", views.quotations, name="sales-quotations"), 
    path("quotations/create/", views.create_quotation, name="sales-create-quotation",), 
    path("quotations/<int:pk>/edit/", views.edit_quotation, name="sales-edit-quotation",),
    path("quotations/<int:pk>/send-whatsapp/", views.send_quotation_whatsapp_view, name="sales-send-quotation-whatsapp",),



    path("quotations/<int:pk>/view/", views.view_quotation, name="sales-view-quotation",),

    # Orders (from a sales perspective) - grouped under orders/
    path("orders/", views.orders, name="sales-orders"),
    path("orders/new/", views.create_order, name="create-order"),
    path("orders/<int:pk>/edit/", views.edit_order, name="edit-order"),
    path("orders/<int:pk>/view/", views.view_order, name="view-order"),
    path("orders/<int:pk>/delete/", views.delete_order, name="delete-order"),

    # AJAX endpoints (keep near related resource if you want)
    path("orders/ajax/products-by-category/", views.ajax_products_by_category, name="ajax-products-by-category"),

    # Invoices - grouped under invoices/
    path("invoices/", views.invoices, name="sales-invoices"),
    path("invoices/<int:pk>/view/", views.view_invoice, name="view-invoice"),

    # Commission & tickets
    path("commission/", views.commission, name="sales-commission"),
    path("commission/<int:pk>/", views.commission_view, name="sales-commission-view"),
    path("commission/email-statement/", views.send_commission_statement_email, name="email-commission-statement"),
    path("targets/", views.target_list, name="sales-target-list"),
    path("targets/add/", views.add_target, name="sales-add-target"),
    path("supervisors/<int:user_id>/", views.supervisor_detail, name="supervisor-detail"),
    path("reps/<int:user_id>/", views.rep_detail, name="rep-detail"),

    path("tickets/", views.tickets, name="sales-tickets"),
    path("tickets/<int:pk>/view/", views.view_ticket, name="view-ticket"),


    # Sales rep profile
    path("profile/", views.profile, name="sales-profile"),

    path(
        "jobs/sales-representative/",
        views.sales_job,
        name="sales-job",
    ), 

    path(
        "sales-job/thank-you/",
        views.sales_job_thank_you,
        name="sales-job-thank-you",
    ),
    path("quotations/<int:pk>/send-email/", views.send_quotation_email_internal, name="sales-send-quotation-email",),


    path("quotations/<int:pk>/send-sms/", views.send_quotation_sms, name="sales-send-quotation-sms",),
    path("invoices/<int:pk>/send-email/", views.send_invoice_email_internal, name="sales-send-invoice-email",),
    path("invoices/<int:pk>/send-whatsapp/", views.send_invoice_whatsapp_view, name="sales-send-invoice-whatsapp",),
    path("invoices/<int:pk>/send-sms/", views.send_invoice_sms_view, name="sales-send-invoice-sms",),

    path("commission/rep/<int:user_id>/", views.commission_rep_detail, name="sales-commission-rep-detail",),
    path("tickets/create/", views.create_ticket, name="sales-create-ticket",),


]
