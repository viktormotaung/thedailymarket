from django.urls import path
from . import views

app_name = "sales"

urlpatterns = [
    # Main sales dashboard
    path("", views.sales_dashboard, name="sales-dashboard"),
    path("leads/", views.leads, name="sales-leads"),
    path( "leads/add/", views.lead_create, name="sales-lead-create", ),
    path( "leads/<int:pk>/", views.lead_view, name="sales-lead-view", ),
    path("leads/<int:pk>/edit/", views.lead_edit, name="sales-lead-edit",),
    path("leads/<int:pk>/convert-to-prospect/", views.lead_convert_to_prospect, name="lead-convert-to-prospect",),
    path("prospects/", views.prospects, name="sales-prospects"),
    
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
    path("invoices/<int:pk>/confirm-payment/", views.invoice_confirm_payment, name="sales-invoice-confirm-payment"),
    path("invoices/<int:pk>/download/", views.invoice_download, name="sales-invoice-download"),
    path("invoices/<int:pk>/payment-request/", views.send_invoice_payment_request, name="sales-send-invoice-payment-request"),
    path("invoices/<int:pk>/payment-request/email/", views.send_invoice_payment_request_email, name="sales-send-invoice-payment-request-email"),
    path("invoices/<int:pk>/payment-request/whatsapp/", views.send_invoice_payment_request_whatsapp, name="sales-send-invoice-payment-request-whatsapp"),
    path("invoices/<int:pk>/payment-request/sms/", views.send_invoice_payment_request_sms, name="sales-send-invoice-payment-request-sms"),

    path("commission/rep/<int:user_id>/", views.commission_rep_detail, name="sales-commission-rep-detail",),
    path("tickets/create/", views.create_ticket, name="sales-create-ticket",),

    # =============================================================================
    # SALES PRODUCT KNOWLEDGE
    # =============================================================================

    path(
        "sales-knowledge/",
        views.sales_knowledge_list,
        name="sales-knowledge-list",
    ),

    path(
        "sales-knowledge/<int:pk>/",
        views.sales_product_knowledge_detail,
        name="sales-knowledge-detail",
    ),

    path(
        "sales-knowledge/compare/",
        views.sales_knowledge_compare,
        name="sales-knowledge-compare",
    ),

    # ============================================================
    # LEAD GEOGRAPHY AJAX
    # ============================================================

    path(
        "leads/ajax/territories-by-region/",
        views.ajax_territories_by_region,
        name="ajax-territories-by-region",
    ),

    path(
        "leads/ajax/areas-by-territory/",
        views.ajax_areas_by_territory,
        name="ajax-areas-by-territory",
    ),

    path("funeral-consultant/", views.funeral_consultant_dashboard, name="funeral-consultant-dashboard",),

    path(
        "funeral-consultant/customers/",
        views.funeral_customers,
        name="funeral-customers",
    ),

    path(
        "funeral-consultant/customers/add/",
        views.funeral_customer_create,
        name="funeral-customer-create",
    ),

    path(
        "funeral-consultant/customers/<int:pk>/",
        views.funeral_customer_detail,
        name="funeral-customer-detail",
    ),

    path(
        "funeral-consultant/quotations/",
        views.funeral_quotations,
        name="funeral-quotations",
    ),
    path(
        "funeral-consultant/quotations/add/",
        views.funeral_quotation_create,
        name="funeral-quotation-create",
    ),
    path(
        "funeral-consultant/quotations/<int:pk>/",
        views.funeral_quotation_detail,
        name="funeral-quotation-detail",
    ),
    path(
        "funeral-consultant/quotations/<int:pk>/edit/",
        views.funeral_quotation_edit,
        name="funeral-quotation-edit",
    ),

    path(
        "funeral-consultant/orders/",
        views.funeral_orders,
        name="funeral-orders",
    ),
    path(
        "funeral-consultant/orders/add/",
        views.funeral_order_create,
        name="funeral-order-create",
    ),
    path(
        "funeral-consultant/orders/<int:pk>/",
        views.funeral_order_detail,
        name="funeral-order-detail",
    ),
    path(
        "funeral-consultant/orders/<int:pk>/edit/",
        views.funeral_order_edit,
        name="funeral-order-edit",
    ),

    # ============================================================
    # FUNERAL CONSULTANT — INVOICES
    # ============================================================
    path(
        "funeral-consultant/invoices/",
        views.funeral_invoices,
        name="funeral-invoices",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/",
        views.funeral_invoice_detail,
        name="funeral-invoice-detail",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/send-email/",
        views.funeral_send_invoice_email,
        name="funeral-send-invoice-email",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/send-whatsapp/",
        views.funeral_send_invoice_whatsapp,
        name="funeral-send-invoice-whatsapp",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/send-sms/",
        views.funeral_send_invoice_sms,
        name="funeral-send-invoice-sms",
    ),

    path(
        "funeral-consultant/invoices/<int:pk>/confirm-payment/",
        views.funeral_confirm_payment,
        name="funeral-confirm-payment",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/download/",
        views.funeral_invoice_download,
        name="funeral-invoice-download",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/payment-request/",
        views.funeral_send_payment_request,
        name="funeral-send-payment-request",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/payment-request/email/",
        views.funeral_send_payment_request_email,
        name="funeral-payment-request-email",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/payment-request/whatsapp/",
        views.funeral_send_payment_request_whatsapp,
        name="funeral-payment-request-whatsapp",
    ),
    path(
        "funeral-consultant/invoices/<int:pk>/payment-request/sms/",
        views.funeral_send_payment_request_sms,
        name="funeral-payment-request-sms",
    ),

    # ============================================================
    # FUNERAL CONSULTANT — COMMISSION
    # ============================================================
    path(
        "funeral-consultant/commission/",
        views.funeral_consultant_commission,
        name="funeral-consultant-commission",
    ),
    path(
        "funeral-consultant/commission/<int:pk>/",
        views.funeral_consultant_commission_detail,
        name="funeral-consultant-commission-detail",
    ),

    # ============================================================
    # FUNERAL CONSULTANT — TICKETS
    # ============================================================
    path(
        "funeral-consultant/tickets/",
        views.funeral_tickets,
        name="funeral-tickets",
    ),
    path(
        "funeral-consultant/tickets/add/",
        views.funeral_ticket_create,
        name="funeral-ticket-create",
    ),
    path(
        "funeral-consultant/tickets/<int:pk>/",
        views.funeral_ticket_detail,
        name="funeral-ticket-detail",
    ),

    path(
        "funeral-consultant/quotations/<int:pk>/change-status/",
        views.funeral_quotation_change_status,
        name="funeral-quotation-change-status",
    ),

    path(
        "funeral/quotations/<int:pk>/accept/",
        views.quotation_accept,
        name="funeral-quotation-accept",
    ),
]







