# clients/admin.py
# clients/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Client,
    ClientCompliance,
    ClientComplianceDocument,
    Prospect,
    ProspectUpdate,
    Membership,
    TradePoint,
    Lead,
    LeadActivity,
)


# ============================================================
# CLIENT
# ============================================================

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        "client_number",
        "display_name",
        "sales_operator",
        "area",
        "is_dummy",
        "client_type",
        "price_type",
        "status",
        "account_type",
        "credit_status",
        "city",
        "delivery_city",
        "has_geo",
        "account_manager",
        "last_order_at",
        "created_at",
    )

    list_filter = (
        "sales_operator",
        "area",
        "is_dummy",
        "status",
        "client_type",
        "price_type",
        "account_type",
        "credit_status",
        "province",
        "delivery_province",
        "account_manager",
        ("categories", admin.RelatedOnlyFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
        ("last_order_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "client_number",
        "name",
        "organization",
        "contact_person",
        "email",
        "phone",
        "whatsapp",
        "sales_operator__name",
        "vat_number",
        "registration_identifier",
        "address_line1",
        "suburb",
        "city",
        "delivery_address_line1",
        "delivery_suburb",
        "delivery_city",
    )

    ordering = ("name",)
    list_select_related = ("account_manager", "sales_operator", "funder")
    list_per_page = 50
    save_on_top = True

    readonly_fields = (
        "client_number",
        "created_at",
        "updated_at",
        "last_order_at",
        "maps_link",
    )

    autocomplete_fields = (
        "account_manager",
        "sales_operator",
        "funder",
    )

    filter_horizontal = ("categories",)

    fieldsets = (
        ("Account", {
            "fields": (
                ("client_number", "status"),
                ("client_type", "client_size_tier"),
                ("price_type",),
                ("area", "sales_operator"),
                ("account_type", "credit_status"),
                ("account_manager", "funder"),
                ("is_dummy",),
            )
        }),
        ("Identity", {
            "fields": (
                "name",
                "organization",
                "entity_type",
                "contact_person",
                ("email", "phone", "whatsapp"),
            )
        }),
        ("Billing Address", {
            "fields": (
                "address_line1",
                "address_line2",
                ("suburb", "city"),
                ("province", "postal_code"),
                "country",
            )
        }),
        ("Delivery Address", {
            "fields": (
                "delivery_address_line1",
                "delivery_address_line2",
                ("delivery_suburb", "delivery_city"),
                ("delivery_province", "delivery_postal_code"),
                "delivery_country",
                ("delivery_lat", "delivery_lng"),
                "maps_link",
            )
        }),
        ("Delivery Preferences", {
            "fields": (
                "preferred_delivery_slot_1",
                "preferred_delivery_slot_2",
                "preferred_delivery_slot_3",
            ),
            "classes": ("collapse",),
        }),
        ("Compliance", {
            "fields": (
                "vat_number",
                "registration_identifier",
            ),
            "classes": ("collapse",),
        }),
        ("Categories & Spend", {
            "fields": (
                "categories",
                "estimated_weekly_spend",
            ),
        }),
        ("Notes & Meta", {
            "fields": (
                "notes",
                "last_order_at",
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.path.startswith("/dummy-admin/"):
            return qs.using("dummy")

        return qs.using("default")

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(
            request,
            queryset,
            search_term,
        )

        if request.path.startswith("/dummy-admin/"):
            queryset = queryset.using("dummy")
        else:
            queryset = queryset.using("default")

        return queryset, use_distinct

    @admin.display(description="Name / Org")
    def display_name(self, obj: Client):
        return obj.organization or obj.name

    @admin.display(boolean=True, description="Geo?")
    def has_geo(self, obj: Client):
        return obj.has_delivery_geo

    @admin.display(description="Map")
    def maps_link(self, obj: Client):
        url = obj.google_maps_link()
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open map</a>',
            url,
        )


# ============================================================
# CLIENT COMPLIANCE
# ============================================================

class ClientComplianceDocumentInline(admin.TabularInline):
    model = ClientComplianceDocument
    extra = 0

    fields = (
        "document_type",
        "file",
        "status",
        "reviewed_by",
        "reviewed_at",
        "uploaded_by",
        "uploaded_at",
        "notes",
    )

    readonly_fields = (
        "uploaded_at",
    )

    autocomplete_fields = (
        "uploaded_by",
        "reviewed_by",
    )

    show_change_link = True


@admin.register(ClientCompliance)
class ClientComplianceAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "vetting_status",
        "vetted_by",
        "vetted_at",
        "created_at",
    )

    list_filter = (
        "vetting_status",
        "vetted_by",
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "client__name",
        "client__organization",
        "vat_number",
        "registration_identifier",
        "notes",
    )

    autocomplete_fields = (
        "client",
        "vetted_by",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    inlines = [ClientComplianceDocumentInline]

    fieldsets = (
        ("Client", {
            "fields": (
                "client",
            ),
        }),
        ("Registration", {
            "fields": (
                "registration_identifier",
                "vat_number",
            ),
        }),
        ("Vetting", {
            "fields": (
                "vetting_status",
                ("vetted_by", "vetted_at"),
                "notes",
            )
        }),
        ("Meta", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(ClientComplianceDocument)
class ClientComplianceDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "compliance",
        "document_type",
        "status",
        "reviewed_by",
        "reviewed_at",
        "uploaded_by",
        "uploaded_at",
    )

    list_filter = (
        "document_type",
        "status",
        "reviewed_by",
        "uploaded_by",
        ("uploaded_at", admin.DateFieldListFilter),
        ("reviewed_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "compliance__client__name",
        "compliance__client__organization",
        "notes",
    )

    autocomplete_fields = (
        "compliance",
        "reviewed_by",
        "uploaded_by",
    )

    readonly_fields = (
        "uploaded_at",
    )


# ============================================================
# PROSPECTS
# ============================================================

class ProspectUpdateInline(admin.TabularInline):
    model = ProspectUpdate
    extra = 0
    ordering = ("-action_at",)
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "stage",
        "status",
        "sales_operator",
        "owner",
        "area",
        "city",
        "province",
        "has_geo",
        "estimated_weekly_spend",
        "last_contact_at",
        "created_at",
    )

    list_filter = (
        "stage",
        "status",
        "sales_operator",
        "owner",
        "area",
        "province",
        ("created_at", admin.DateFieldListFilter),
        ("last_contact_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "name",
        "organization",
        "contact_name",
        "email",
        "phone",
        "whatsapp",
        "sales_operator__name",
        "city",
        "lead_source",
        "notes",
    )

    autocomplete_fields = (
        "owner",
        "sales_operator",
        "created_by",
        "client",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "last_contact_at",
        "maps_link",
    )

    date_hierarchy = "created_at"
    list_per_page = 50
    save_on_top = True
    inlines = [ProspectUpdateInline]

    fieldsets = (
        ("Ownership & Pipeline", {
            "fields": (
                ("owner", "created_by"),
                ("sales_operator", "area"),
                ("stage", "status"),
                ("last_contact_at", "next_follow_up_at"),
            )
        }),
        ("Identity", {
            "fields": (
                "name",
                "organization",
                "entity_type",
                "contact_name",
                ("email", "phone", "whatsapp"),
            )
        }),
        ("Location", {
            "fields": (
                "address_line1",
                "address_line2",
                ("suburb", "city"),
                ("province", "postal_code"),
                "country",
                ("lat", "lng"),
                "maps_link",
            ),
        }),
        ("Potential Value", {
            "fields": (
                ("potential_client_type", "potential_size_tier"),
                "categories",
                "estimated_weekly_spend",
                "lead_source",
            )
        }),
        ("Delivery Preferences", {
            "fields": (
                "preferred_delivery_slot_1",
                "preferred_delivery_slot_2",
                "preferred_delivery_slot_3",
            ),
            "classes": ("collapse",),
        }),
        ("Early Compliance", {
            "fields": (
                "vat_number",
                "registration_identifier",
            ),
            "classes": ("collapse",),
        }),
        ("Conversion", {
            "fields": (
                "client",
            ),
        }),
        ("Notes & Meta", {
            "fields": (
                "notes",
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(boolean=True, description="Geo?")
    def has_geo(self, obj: Prospect):
        return obj.has_geo


    @admin.display(description="Map")
    def maps_link(self, obj: Prospect):
        url = obj.google_maps_link()

        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open map</a>',
            url,
        )

    filter_horizontal = ("categories",)


# ============================================================
# PROSPECT UPDATE
# ============================================================

@admin.register(ProspectUpdate)
class ProspectUpdateAdmin(admin.ModelAdmin):
    list_display = (
        "prospect",
        "action_at",
        "action_type",
        "outcome",
        "user",
        "old_stage",
        "new_stage",
        "visit_date",
        "has_photo",
        "short_notes",
    )

    list_filter = (
        "action_type",
        "outcome",
        "old_stage",
        "new_stage",
        "user",
        ("action_at", admin.DateFieldListFilter),
        ("visit_date", admin.DateFieldListFilter),
    )

    search_fields = (
        "prospect__name",
        "prospect__organization",
        "notes",
        "negotiation_products",
        "negotiation_menu_opportunities",
        "negotiation_competitor_info",
        "visit_contact_name",
        "user__username",
    )

    autocomplete_fields = (
        "prospect",
        "user",
    )

    date_hierarchy = "action_at"
    ordering = ("-action_at", "-created_at")

    readonly_fields = (
        "created_at",
    )

    fieldsets = (
        ("Interaction", {
            "fields": (
                "prospect",
                "user",
                "action_type",
                "outcome",
                "action_at",
                ("old_stage", "new_stage"),
                "notes",
                "created_at",
            )
        }),
        ("Site Visit", {
            "fields": (
                "visit_date",
                ("visit_time_arrived", "visit_time_left"),
                "visit_contact_name",
                "visit_photo",
            ),
            "classes": ("collapse",),
        }),
        ("Negotiation", {
            "fields": (
                "negotiation_products",
                "negotiation_menu_opportunities",
                "negotiation_competitor_info",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(boolean=True, description="Photo?")
    def has_photo(self, obj):
        return bool(obj.visit_photo)

    @admin.display(description="Notes")
    def short_notes(self, obj):
        if not obj.notes:
            return ""
        return obj.notes[:50] + ("…" if len(obj.notes) > 50 else "")
    


# ============================================================
# MEMBERSHIP
# ============================================================

@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):

    list_display = (
        "membership_number",
        "display_client",
        "tier",
        "trade_points",
        "lifetime_trade_points",
        "status",
        "source",
        "member_since",
        "days_as_member",
        "applied_at",
        "activated_at",
        "is_test_member",
    )
    list_filter = (
        "tier",
        "status",
        "source",
        "is_test_member",
        ("applied_at", admin.DateFieldListFilter),
        ("activated_at", admin.DateFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "membership_number",
        "client__name",
        "client__organization",
        "client__client_number",
        "client__email",
        "client__phone",
    )

    ordering = (
        "membership_number",
    )

    autocomplete_fields = (
        "client",
    )

    readonly_fields = (
        "membership_number",
        "trade_points",
        "lifetime_trade_points",
        "applied_at",
        "created_at",
        "updated_at",
        "member_since",
        "days_as_member",
    )

    save_on_top = True
    list_per_page = 50

    fieldsets = (

        ("Membership", {
            "fields": (
                "client",
                ("membership_number", "status"),
                ("source", "tier"),
                ("trade_points", "lifetime_trade_points"),
                "is_test_member",
            )
        }),

        ("Lifecycle", {
            "fields": (
                "applied_at",
                "activated_at",
                "suspended_at",
                "cancelled_at",
                "member_since",
                "days_as_member",
            )
        }),

        ("Internal", {
            "fields": (
                "internal_notes",
            )
        }),

        ("Meta", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Client")
    def display_client(self, obj):
        return obj.client.organization or obj.client.name

    @admin.display(description="Member Since")
    def member_since(self, obj):
        return obj.member_since or "-"

    @admin.display(description="Days")
    def days_as_member(self, obj):
        return obj.days_as_member
    
    
    

# ============================================================
# LEADS
# ============================================================

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):

    list_display = (
        "lead_number",
        "display_name",
        "contact_person",
        "phone",
        "potential_client_type",
        "status",
        "priority",
        "source",
        "preferred_call_time",
        "area",
        "province",
        "assigned_to",
        "is_converted_display",
        "created_at",
    )

    list_filter = (
        "status",
        "priority",
        "source",
        "potential_client_type",
        "preferred_call_time",
        "area",
        "province",
        "assigned_to",
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "lead_number",
        "business_name",
        "contact_person",
        "phone",
        "whatsapp",
        "email",
        "campaign",
        "advert",
        "notes",
    )

    ordering = (
        "-created_at",
    )

    list_per_page = 50
    save_on_top = True

    autocomplete_fields = (
        "assigned_to",
        "created_by",
        "prospect",
    )

    readonly_fields = (
        "lead_number",
        "created_at",
        "updated_at",
        "preferred_call_time_selected_at",
        "is_converted_display",
        "age_days",
    )

    filter_horizontal = (
        "interested_in",
    )

    fieldsets = (

        (
            "Lead",
            {
                "fields": (
                    ("lead_number", "status"),
                    ("priority", "source"),
                    ("assigned_to", "created_by"),
                )
            },
        ),

        (
            "Marketing",
            {
                "fields": (
                    "campaign",
                    "advert",
                    "medium",
                )
            },
        ),

        (
            "Business",
            {
                "fields": (
                    "business_name",
                    ("entity_type", "potential_client_type"),
                    "estimated_weekly_spend",
                    "interested_in",
                )
            },
        ),

        (
            "Contact",
            {
                "fields": (
                    "contact_person",
                    ("phone", "whatsapp"),
                    "email",
                )
            },
        ),

        (
            "Location",
            {
                "fields": (
                    "address_line1",
                    "address_line2",
                    ("suburb", "city"),
                    ("province", "postal_code"),
                    "country",
                    "area",
                )
            },
        ),

        (
            "Sales Activity",
            {
                "fields": (
                    ("preferred_call_time", "preferred_call_time_selected_at"),
                    ("last_contact_at", "next_follow_up_at"),
                    "notes",
                )
            },
        ),

        (
            "Conversion",
            {
                "fields": (
                    "prospect",
                    "is_converted_display",
                )
            },
        ),

        (
            "Meta",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "age_days",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Business")
    def display_name(self, obj):
        return obj.business_name or obj.contact_person

    @admin.display(boolean=True, description="Converted")
    def is_converted_display(self, obj):
        return obj.is_converted
    

@admin.register(LeadActivity)
class LeadActivityAdmin(admin.ModelAdmin):

    list_display = (
        "lead",
        "occurred_at",
        "activity_type",
        "outcome",
        "user",
        "short_notes",
    )

    list_filter = (
        "activity_type",
        "outcome",
        "user",
        ("occurred_at", admin.DateFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "lead__lead_number",
        "lead__business_name",
        "lead__contact_person",
        "notes",
        "user__username",
        "user__first_name",
        "user__last_name",
    )

    ordering = (
        "-occurred_at",
        "-created_at",
    )

    date_hierarchy = "occurred_at"

    list_per_page = 50
    save_on_top = True

    autocomplete_fields = (
        "lead",
        "user",
    )

    readonly_fields = (
        "created_at",
    )

    fieldsets = (

        ("Lead Activity", {
            "fields": (
                "lead",
                "user",
                ("activity_type", "outcome"),
                "occurred_at",
                "notes",
            )
        }),

        ("Meta", {
            "fields": (
                "created_at",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Notes")
    def short_notes(self, obj):

        if not obj.notes:
            return "-"

        if len(obj.notes) <= 75:
            return obj.notes

        return obj.notes[:75] + "..."
    
class LeadActivityInline(admin.TabularInline):
    model = LeadActivity
    extra = 0

    ordering = (
        "-occurred_at",
    )

    autocomplete_fields = (
        "user",
    )

    readonly_fields = (
        "created_at",
    )

    show_change_link = True

    fields = (
        "occurred_at",
        "activity_type",
        "outcome",
        "user",
        "notes",
        "created_at",
    )   



# ============================================================
# TRADE POINTS
# ============================================================

@admin.register(TradePoint)
class TradePointAdmin(admin.ModelAdmin):

    list_display = (
        "created_at",
        "display_member",
        "transaction_type",
        "reason",
        "signed_points_display",
        "balance_after",
        "reference",
        "created_by",
    )

    list_filter = (
        "transaction_type",
        "reason",
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "membership__membership_number",
        "membership__client__name",
        "membership__client__organization",
        "reference",
        "notes",
    )

    ordering = (
        "-created_at",
        "-id",
    )

    autocomplete_fields = (
        "membership",
        "created_by",
    )

    date_hierarchy = "created_at"

    list_per_page = 50
    save_on_top = True

    readonly_fields = (
        "membership",
        "transaction_type",
        "reason",
        "points",
        "balance_after",
        "reference",
        "notes",
        "created_by",
        "created_at",
    )

    fieldsets = (

        ("Trade Point", {
            "fields": (
                "membership",
                ("transaction_type", "reason"),
                ("points", "balance_after"),
                "reference",
                "notes",
            )
        }),

        ("Audit", {
            "fields": (
                "created_by",
                "created_at",
            )
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Member")
    def display_member(self, obj):
        return obj.membership.membership_number

    @admin.display(description="Movement")
    def signed_points_display(self, obj):
        sign = "+" if obj.is_credit else "-"
        return f"{sign}{obj.points}"