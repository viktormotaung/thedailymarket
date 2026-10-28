# clients/admin.py
from django.contrib import admin
from django.utils.html import format_html, format_html_join

from .models import (
    Client,
    Region,
    Territory,
    Area,
    ClientCompliance,
    ClientComplianceDocument,
    Prospect,
    ProspectUpdate,
    Membership,
    TradePoint,
    Lead,
    LeadActivity,
    EndUser,
    SampleRequest,
    SampleRequestItem,
    Campaign,
    CampaignQuestion,
    CampaignResponse,
    CampaignResponseAnswer,
    CampaignSMSConfirmation,
)

# ============================================================
# GEOGRAPHY
# ============================================================

class TerritoryInline(admin.TabularInline):
    model = Territory
    extra = 0
    fields = (
        "name",
        "code",
        "status",
    )
    show_change_link = True


class AreaInline(admin.TabularInline):
    model = Area
    extra = 1
    fields = (
        "name",
        "code",
        "status",
    )
    show_change_link = True


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "status",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "name",
        "code",
    )

    ordering = (
        "name",
    )

    inlines = (
        TerritoryInline,
    )


@admin.register(Territory)
class TerritoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "region",
        "status",
    )

    list_filter = (
        "region",
        "status",
    )

    search_fields = (
        "name",
        "code",
        "region__name",
    )

    ordering = (
        "region__name",
        "name",
    )

    inlines = (
        AreaInline,
    )


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "territory",
        "status",
    )

    list_filter = (
        "territory__region",
        "territory",
        "status",
    )

    search_fields = (
        "name",
        "code",
        "territory__name",
        "territory__region__name",
    )

    ordering = (
        "territory__region__name",
        "territory__name",
        "name",
    )









# ============================================================
# CLIENT
# ============================================================


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
        "region",
        "territory",
        "area",
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

   

    fieldsets = (
        ("Account", {
            "fields": (
                ("client_number", "status"),
                ("client_type", "client_size_tier"),
                ("price_type",),
                ("region", "territory"),
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
        ("Products & Spend", {
            "fields": (
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
        "region",
        "territory",
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
        "region",
        "territory",
        "area",
        "province",
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

    list_per_page = 50
    save_on_top = True
    inlines = [ProspectUpdateInline]

    fieldsets = (
        ("Ownership & Pipeline", {
            "fields": (
                ("owner", "created_by"),
                ("sales_operator", "region"),
                ("territory", "area"),
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
# SAMPLE REQUESTS
# ============================================================

class SampleRequestItemInline(admin.TabularInline):
    model = SampleRequestItem
    extra = 0
    autocomplete_fields = ("product",)
    fields = (
        "product",
        "quantity",
        "created_at",
    )
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(SampleRequest)
class SampleRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "prospect",
        "requested_by",
        "requested_at",
        "status",
        "expected_date",
        "task",
        "created_at",
    )

    list_filter = (
        "status",
        ("requested_at", admin.DateFieldListFilter),
        ("expected_date", admin.DateFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "prospect__name",
        "prospect__organization",
        "requested_by__username",
        "requested_by__first_name",
        "requested_by__last_name",
        "notes",
    )

    ordering = (
        "-requested_at",
        "-created_at",
    )

    list_per_page = 50
    save_on_top = True

    autocomplete_fields = (
        "prospect",
        "requested_by",
        "task",
    )

    readonly_fields = (
        "requested_at",
        "expected_date",
        "task",
        "created_at",
        "updated_at",
    )

    inlines = (
        SampleRequestItemInline,
    )

    fieldsets = (
        ("Sample Request", {
            "fields": (
                "prospect",
                "requested_by",
                ("status", "expected_date"),
                "notes",
            ),
        }),

        ("Task", {
            "fields": (
                "task",
            ),
        }),

        ("Meta", {
            "fields": (
                "requested_at",
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(SampleRequestItem)
class SampleRequestItemAdmin(admin.ModelAdmin):
    list_display = (
        "sample_request",
        "product",
        "quantity",
        "created_at",
    )

    list_filter = (
        "product",
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "sample_request__prospect__name",
        "sample_request__prospect__organization",
        "product__product_no",
        "product__name",
        "product__sku",
    )

    ordering = (
        "-created_at",
        "product__name",
    )

    list_per_page = 50

    autocomplete_fields = (
        "sample_request",
        "product",
    )

    readonly_fields = (
        "created_at",
    )

    fieldsets = (
        ("Sample Item", {
            "fields": (
                "sample_request",
                "product",
                "quantity",
            ),
        }),

        ("Meta", {
            "fields": (
                "created_at",
            ),
            "classes": ("collapse",),
        }),
    )




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
        "region",
        "territory",
        "area",
        "province",
        "location_status",
        "assigned_to",
        "is_converted_display",
    )

    list_filter = (
        "status",
        "priority",
        "source",
        "potential_client_type",
        "preferred_call_time",
        "region",
        "territory",
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
        "latitude",
        "longitude",
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
        "updated_at",
        "preferred_call_time_selected_at",
        "is_converted_display",
        "age_days",
        "location_captured_at",
        "campaign_questions_answers",
    )

    fieldsets = (

        # =====================================================
        # LEAD
        # =====================================================

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

        # =====================================================
        # MARKETING
        # =====================================================

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

        # =====================================================
        # BUSINESS
        # =====================================================

        (
            "Business",
            {
                "fields": (
                    "business_name",
                    ("entity_type", "potential_client_type"),
                    "estimated_weekly_spend",
                )
            },
        ),

        # =====================================================
        # CONTACT
        # =====================================================

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

        # =====================================================
        # LOCATION
        # =====================================================

        (
            "Location",
            {
                "fields": (
                    "address_line1",
                    "address_line2",
                    ("suburb", "city"),
                    ("province", "postal_code"),
                    "country",
                    ("region", "territory"),
                    "area",

                    # GPS LOCATION
                    ("latitude", "longitude"),
                    "location_captured_at",
                )
            },
        ),

        # =====================================================
        # SALES ACTIVITY
        # =====================================================

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

        # =====================================================
        # CAMPAIGN QUESTIONS & ANSWERS
        # =====================================================

        (
            "Campaign Questions & Answers",
            {
                "fields": (
                    "campaign_questions_answers",
                )
            },
        ),

        # =====================================================
        # CONVERSION
        # =====================================================

        (
            "Conversion",
            {
                "fields": (
                    "prospect",
                    "is_converted_display",
                )
            },
        ),

        # =====================================================
        # META
        # =====================================================

        (
            "Meta",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "age_days",
                ),
            },
        ),
    )

    # =========================================================
    # DISPLAY NAME
    # =========================================================

    @admin.display(description="Business")
    def display_name(self, obj):
        return obj.business_name or obj.contact_person

    # =========================================================
    # CONVERTED STATUS
    # =========================================================

    @admin.display(
        boolean=True,
        description="Converted"
    )
    def is_converted_display(self, obj):
        return obj.is_converted

    # =========================================================
    # GPS STATUS
    # =========================================================

    @admin.display(description="Campaign Questions & Answers")
    def campaign_questions_answers(self, obj):
        """Display questionnaire answers directly on the Lead admin record."""
        responses = (
            obj.campaign_responses
            .all()
            .prefetch_related("answers")
            .order_by("-submitted_at", "-id")
        )

        if not responses.exists():
            return "No campaign questionnaire responses recorded for this lead."

        response_blocks = []
        for response in responses:
            answer_rows = []
            for answer in response.answers.all():
                question = (
                    answer.question_text_snapshot
                    or answer.question.question_text
                    or "Question"
                )
                value = answer.answer_value

                if value in (None, "", [], {}):
                    display_value = "—"
                elif isinstance(value, list):
                    display_value = ", ".join(map(str, value))
                elif isinstance(value, dict):
                    display_value = str(value)
                else:
                    display_value = str(value)

                answer_rows.append((question, display_value))

            if answer_rows:
                answer_html = format_html_join(
                    "",
                    '<div style="padding:6px 0;border-bottom:1px solid #eee;">'
                    '<strong>{}</strong><br>{}</div>',
                    answer_rows,
                )
            else:
                answer_html = format_html(
                    '<p style="color:#777;">No answers were saved for this submission.</p>'
                )

            response_blocks.append(
                format_html(
                    '<div style="margin:0 0 18px;padding:12px;border:1px solid #ddd;'
                    'border-radius:6px;">'
                    '<div style="font-weight:600;margin-bottom:8px;">{}</div>{}</div>',
                    f"{response.campaign.name} — {response.submitted_at:%d %b %Y, %H:%M}",
                    answer_html,
                )
            )

        return format_html_join(" ", "{}", ((block,) for block in response_blocks))

    @admin.display(
        boolean=True,
        description="GPS"
    )
    def location_status(self, obj):
        return bool(
            obj.latitude is not None
            and obj.longitude is not None
        )

    

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




# ============================================================
# END USERS
# ============================================================

@admin.register(EndUser)
class EndUserAdmin(admin.ModelAdmin):
    list_display = (
        "end_user_number",
        "full_name_display",
        "client",
        "end_user_type",
        "phone",
        "city",
        "status",
        "account_manager",
        "created_at",
    )

    list_filter = (
        "end_user_type",
        "status",
        "client",
        "city",
        "province",
        "account_manager",
        ("created_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "end_user_number",
        "first_name",
        "surname",
        "phone",
        "whatsapp",
        "email",
        "client__client_number",
        "client__name",
        "client__organization",
    )

    ordering = (
        "client",
        "surname",
        "first_name",
    )

    list_per_page = 50
    save_on_top = True

    autocomplete_fields = (
        "client",
        "account_manager",
    )

    readonly_fields = (
        "end_user_number",
        "created_at",
        "updated_at",
        "maps_link",
    )

    fieldsets = (
        ("End User", {
            "fields": (
                ("end_user_number", "status"),
                ("end_user_type",),
                "client",
            ),
        }),

        ("Identity", {
            "fields": (
                ("first_name", "surname"),
            ),
        }),

        ("Contact", {
            "fields": (
                ("phone", "whatsapp"),
                "email",
            ),
        }),

        ("Delivery / Fulfilment Address", {
            "fields": (
                "address_line1",
                "address_line2",
                ("suburb", "city"),
                ("province", "postal_code"),
                "country",
                ("latitude", "longitude"),
                "maps_link",
            ),
        }),

        ("Internal Ownership", {
            "fields": (
                "account_manager",
            ),
        }),

        ("Notes", {
            "fields": (
                "notes",
            ),
        }),

        ("Meta", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Name")
    def full_name_display(self, obj):
        return obj.full_name

    @admin.display(description="Map")
    def maps_link(self, obj):
        if not obj.has_geo:
            return "-"

        return format_html(
            '<a href="https://www.google.com/maps/search/?api=1&query={},{}" '
            'target="_blank" rel="noopener">Open map</a>',
            obj.latitude,
            obj.longitude,
        )

# ============================================================
# MARKETING CAMPAIGNS
# ============================================================

class CampaignQuestionInline(admin.StackedInline):
    """Configure each campaign question, including its dropdown options."""
    model = CampaignQuestion
    extra = 0
    fields = (
        ("sort_order", "is_active"),
        "question_text",
        "question_key",
        "question_type",
        "options",
        "is_required",
        "help_text",
    )
    show_change_link = True
    ordering = ("sort_order", "id")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "campaign_type",
        "objective",
        "status",
        "display_channels",
        # date_hierarchy = "start_date"
        "end_date",
        "budget",
        "response_count",
        "created_at",
    )
    list_filter = (
        "campaign_type",
        "objective",
        "status",
        "start_date",
        "end_date",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "name",
        "code",
        "description",
        "target_audience",
        "offer",
        "form_title",
    )
    ordering = ("-created_at",)
    # Date hierarchy intentionally omitted here. Campaigns can have nullable
    # start/end dates; the date filters above remain available in the sidebar.
    list_per_page = 50
    save_on_top = True
    autocomplete_fields = ("created_by",)
    readonly_fields = ("created_at", "updated_at", "response_count")
    inlines = (CampaignQuestionInline,)
    fieldsets = (
        ("Campaign identity", {
            "fields": (
                ("name", "code"),
                ("campaign_type", "objective", "status"),
                "description",
                "target_audience",
            )
        }),
        ("Channels and offer", {
            "fields": (
                "channels",
                "offer",
            )
        }),
        ("Schedule and budget", {
            "fields": (
                ("start_date", "end_date"),
                "budget",
            )
        }),
        ("Landing page form", {
            "fields": (
                "form_title",
                "form_description",
            )
        }),
        ("Administration", {
            "fields": (
                "created_by",
                "response_count",
                ("created_at", "updated_at"),
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Channels")
    def display_channels(self, obj):
        if not obj.channels:
            return "-"
        labels = dict(Campaign.CHANNEL_CHOICES)
        return ", ".join(labels.get(channel, str(channel)) for channel in obj.channels)

    @admin.display(description="Responses")
    def response_count(self, obj):
        if not obj.pk:
            return 0
        return obj.responses.count()


# ============================================================
# CAMPAIGN QUESTIONS
# ============================================================

@admin.register(CampaignQuestion)
class CampaignQuestionAdmin(admin.ModelAdmin):
    list_display = (
        "question_text",
        "campaign",
        "question_key",
        "question_type",
        "is_required",
        "is_active",
        "sort_order",
        "updated_at",
    )
    list_filter = (
        "campaign",
        "question_type",
        "is_required",
        "is_active",
    )
    search_fields = (
        "question_text",
        "question_key",
        "campaign__name",
        "campaign__code",
    )
    ordering = ("campaign__name", "sort_order", "id")
    autocomplete_fields = ("campaign",)
    list_select_related = ("campaign",)
    list_per_page = 50
    save_on_top = True
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Question", {
            "fields": (
                "campaign",
                "question_text",
                "question_key",
                "question_type",
                "options",
            )
        }),
        ("Form behaviour", {
            "fields": (
                ("is_required", "is_active"),
                ("sort_order",),
                "help_text",
            )
        }),
        ("Meta", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


# ============================================================
# CAMPAIGN RESPONSES / ATTRIBUTION
# ============================================================

class CampaignResponseAnswerInline(admin.TabularInline):
    model = CampaignResponseAnswer
    extra = 0
    fields = (
        "question",
        "question_text_snapshot",
        "answer_value",
        "created_at",
    )
    readonly_fields = ("question_text_snapshot", "created_at")
    autocomplete_fields = ("question",)
    show_change_link = True


class CampaignSMSConfirmationInline(admin.StackedInline):
    model = CampaignSMSConfirmation
    extra = 0
    max_num = 1
    can_delete = False
    fields = (
        "phone_number",
        "provider",
        "status",
        "provider_message_id",
        "attempt_count",
        "idempotency_key",
        "queued_at",
        "last_attempt_at",
        "sent_at",
        "delivered_at",
        "last_error",
        "message",
    )
    readonly_fields = (
        "phone_number",
        "provider",
        "status",
        "provider_message_id",
        "attempt_count",
        "idempotency_key",
        "queued_at",
        "last_attempt_at",
        "sent_at",
        "delivered_at",
        "last_error",
        "message",
    )


@admin.register(CampaignResponse)
class CampaignResponseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "campaign",
        "lead",
        "channel",
        "consent_to_contact",
        "submitted_at",
        "utm_source",
        "utm_campaign",
        "sms_status",
    )
    list_filter = (
        "campaign",
        "channel",
        "consent_to_contact",
        ("submitted_at", admin.DateFieldListFilter),
        "utm_source",
        "utm_medium",
    )
    search_fields = (
        "campaign__name",
        "campaign__code",
        "lead__lead_number",
        "lead__business_name",
        "lead__contact_person",
        "lead__phone",
        "lead__email",
        "advert_reference",
        "utm_source",
        "utm_campaign",
        "fbclid",
        "ttclid",
    )
    ordering = ("-submitted_at", "-id")
    date_hierarchy = "submitted_at"
    list_select_related = ("campaign", "lead")
    autocomplete_fields = ("campaign", "lead")
    readonly_fields = ("submitted_at", "created_at", "sms_status")
    inlines = (CampaignResponseAnswerInline, CampaignSMSConfirmationInline)
    list_per_page = 50
    save_on_top = True
    fieldsets = (
        ("Submission", {
            "fields": (
                ("campaign", "lead"),
                ("channel", "advert_reference"),
                "landing_page",
                ("submitted_at", "created_at"),
            )
        }),
        ("Contact consent", {
            "fields": (
                "consent_to_contact",
                "consent_text",
            )
        }),
        ("Advertising attribution", {
            "fields": (
                ("utm_source", "utm_medium"),
                ("utm_campaign", "utm_content", "utm_term"),
                ("fbclid", "ttclid"),
                "metadata",
            ),
            "classes": ("collapse",),
        }),
        ("SMS confirmation", {
            "fields": ("sms_status",),
        }),
    )

    @admin.display(description="SMS status")
    def sms_status(self, obj):
        if not obj.pk:
            return "-"
        try:
            sms = obj.sms_confirmation
        except CampaignSMSConfirmation.DoesNotExist:
            return "Not queued"
        return sms.get_status_display()


# ============================================================
# CAMPAIGN RESPONSE ANSWERS
# ============================================================

@admin.register(CampaignResponseAnswer)
class CampaignResponseAnswerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "response",
        "question",
        "short_answer",
        "created_at",
    )
    list_filter = (
        "question__campaign",
        "question__question_type",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "response__campaign__name",
        "response__lead__lead_number",
        "response__lead__business_name",
        "question__question_text",
        "question_text_snapshot",
    )
    ordering = ("-created_at",)
    autocomplete_fields = ("response", "question")
    list_select_related = ("response", "question", "question__campaign")
    readonly_fields = ("question_text_snapshot", "created_at", "updated_at")
    list_per_page = 50

    @admin.display(description="Answer")
    def short_answer(self, obj):
        value = obj.answer_value
        if value in (None, "", [], {}):
            return "-"
        answer = str(value)
        return answer if len(answer) <= 90 else answer[:87] + "..."


# ============================================================
# SMS CONFIRMATIONS
# ============================================================

@admin.register(CampaignSMSConfirmation)
class CampaignSMSConfirmationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "response",
        "phone_number",
        "provider",
        "status",
        "attempt_count",
        "provider_message_id",
        "queued_at",
        "sent_at",
        "delivered_at",
    )
    list_filter = (
        "status",
        "provider",
        ("queued_at", admin.DateFieldListFilter),
        ("sent_at", admin.DateFieldListFilter),
        ("delivered_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "phone_number",
        "idempotency_key",
        "provider_message_id",
        "response__campaign__name",
        "response__lead__lead_number",
        "response__lead__business_name",
        "response__lead__phone",
        "last_error",
    )
    ordering = ("-queued_at", "-id")
    date_hierarchy = "queued_at"
    autocomplete_fields = ("response",)
    list_select_related = ("response", "response__campaign", "response__lead")
    readonly_fields = (
        "response",
        "phone_number",
        "message",
        "provider",
        "status",
        "idempotency_key",
        "provider_message_id",
        "attempt_count",
        "last_error",
        "queued_at",
        "last_attempt_at",
        "sent_at",
        "delivered_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Confirmation", {
            "fields": (
                "response",
                "phone_number",
                "provider",
                "status",
                "message",
            )
        }),
        ("Provider and retry tracking", {
            "fields": (
                "idempotency_key",
                "provider_message_id",
                "attempt_count",
                "last_error",
            )
        }),
        ("Timestamps", {
            "fields": (
                "queued_at",
                "last_attempt_at",
                "sent_at",
                "delivered_at",
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        # SMS records should be created by the campaign submission/SMS service.
        return False

    def has_delete_permission(self, request, obj=None):
        # Preserve the SMS audit trail.
        return False
