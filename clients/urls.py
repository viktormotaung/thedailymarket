from django.urls import path
from . import views

urlpatterns = [
    path("", views.client_list, name="staff-clients"),
    path("new/", views.client_create, name="client-create"),
    path("<int:pk>/edit/", views.client_edit, name="client-edit"),


    path("dashboard/", views.client_dashboard, name="client-dashboard"), 
    path("prospects/", views.prospects, name="staff-prospects"),
    path("prospects/<int:pk>/", views.prospect_detail, name="staff-prospect-detail"),

    path(
        "<int:pk>/compliance/edit/",
        views.client_compliance_edit,
        name="client-compliance-edit", 
    ),
    path("<int:pk>/view/", views.client_view, name="client-view"),
    path("<int:pk>/operations/edit/", views.client_edit_operations, name="client-edit-operations"),
    path("membership/", views.membership_list, name="membership-list",),
    path("membership/new/", views.membership_create, name="membership-create",),
    path("membership/<int:client_id>/link/", views.membership_link, name="membership-link",),
    path("membership/<int:membership_id>/delink/", views.membership_delink, name="membership-delink",),
    path("membership/<int:pk>/", views.membership_view, name="membership-view",),
    path("membership/<int:pk>/edit/", views.membership_edit, name="membership-edit",),
    path("leads/", views.leads_list, name="leads-list",),
    path("leads/<int:pk>/", views.lead_view, name="lead-view",),
    path("leads/<int:pk>/edit/", views.lead_edit, name="lead-edit",),
    path("api/respondio/lead/", views.respondio_create_lead, name="respondio-create-lead",),

]
