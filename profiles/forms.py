from django import forms
from .models import CustomerProfile
from django.contrib.auth import get_user_model
from .models import (
    SalesRepProfile,
    SalesRole,
    SalesOperator,
    StaffProfile,
    DriverProfile,
)

from clients.models import Region, Territory


class PersonalProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = [
            "display_name",
            "phone",
        ]

        widgets = {
            "display_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "How we should address you",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. 082 123 4567",
            }),
        }







User = get_user_model()


class SalesRepProfileForm(forms.ModelForm):
    class Meta:
        model = SalesRepProfile

        fields = [
            "status",
            "sales_operator",
            "region",
            "territory",
            "base_commission_pct",
            "bonus_commission_pct",
            "department",
            "roles",
            "supervisor",
            "notes",
        ]

        widgets = {
            "status": forms.Select(attrs={
                "class": "form-select",
            }),
            "sales_operator": forms.Select(attrs={
                "class": "form-select",
            }),

            "region": forms.Select(attrs={
                "class": "form-select",
            }),

            "territory": forms.Select(attrs={
                "class": "form-select",
            }),
            "base_commission_pct": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
            }),
            "bonus_commission_pct": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
            }),
            "department": forms.TextInput(attrs={
                "class": "form-control",
                "readonly": "readonly",
            }),
            "roles": forms.CheckboxSelectMultiple(),
            "supervisor": forms.Select(attrs={
                "class": "form-select",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        

        # --------------------------------------------------
        # Region
        # --------------------------------------------------
        self.fields["region"].queryset = (
            Region.objects
            .filter(status="ACTIVE")
            .order_by("name")
        )

        # --------------------------------------------------
        # Territory
        # --------------------------------------------------
        self.fields["territory"].queryset = (
            Territory.objects
            .select_related("region")
            .order_by("name")
        )

        # If a region has been selected, only show
        # territories belonging to that region.
        region_id = self.data.get("region") or getattr(
            self.instance,
            "region_id",
            None,
        )

        if region_id:
            self.fields["territory"].queryset = (
                Territory.objects
                .filter(
                    status="ACTIVE",
                    region_id=region_id,
                )
                .select_related("region")
                .order_by("name")
            )

        # --------------------------------------------------
        # Sales Operator
        # --------------------------------------------------
        self.fields["sales_operator"].queryset = (
            SalesOperator.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # --------------------------------------------------
        # Roles
        # --------------------------------------------------
        self.fields["roles"].queryset = (
            SalesRole.objects
            .all()
            .order_by("name")
        )

        # --------------------------------------------------
        # Supervisors
        # --------------------------------------------------
        supervisor_qs = (
            User.objects
            .filter(
                is_staff=True,
                sales_rep_profile__roles__code="supervisor",
            )
            .select_related("sales_rep_profile")
            .distinct()
            .order_by("first_name", "last_name", "username")
        )

        # Restrict supervisors to the selected region.
        if region_id:
            supervisor_qs = supervisor_qs.filter(
                sales_rep_profile__region_id=region_id
            )

        # Don't allow a user to supervise themselves.
        if self.instance and self.instance.pk:
            supervisor_qs = supervisor_qs.exclude(
                pk=self.instance.user_id
            )

        # --------------------------------------------------
        # Supervisor
        # --------------------------------------------------

        # Keep the real supervisors in the database.
        self.fields["supervisor"].queryset = supervisor_qs

        # Add an explicit N/A option for a top-level supervisor.
        self.fields["supervisor"].empty_label = "N/A – Self / Top-Level Supervisor"

        # --------------------------------------------------
        # Required / optional fields
        # --------------------------------------------------
        self.fields["sales_operator"].required = False
        self.fields["region"].required = False
        self.fields["territory"].required = False
        self.fields["roles"].required = False
        self.fields["supervisor"].required = False
        self.fields["notes"].required = False


    def clean(self):
        cleaned = super().clean()

        roles = cleaned.get("roles")
        region = cleaned.get("region")
        territory = cleaned.get("territory")
        supervisor = cleaned.get("supervisor")

        role_codes = set(
            roles.values_list("code", flat=True)
        ) if roles else set()

        is_rep = "rep" in role_codes
        is_supervisor = "supervisor" in role_codes

        # --------------------------------------------------
        # Supervisor
        # --------------------------------------------------
        if is_supervisor:
            if not region:
                self.add_error(
                    "region",
                    "A supervisor must be assigned to a region."
                )

            if territory:
                self.add_error(
                    "territory",
                    "A supervisor is assigned at Region level and should not have a territory."
                )

            if supervisor:
                self.add_error(
                    "supervisor",
                    "A supervisor cannot report to another supervisor."
                )

        # --------------------------------------------------
        # Sales Rep
        # --------------------------------------------------
        if is_rep:
            if not territory:
                self.add_error(
                    "territory",
                    "A sales rep must be assigned to a territory."
                )

            if not supervisor:
                self.add_error(
                    "supervisor",
                    "A sales rep must have a supervisor."
                )

            if territory:
                # The territory determines the rep's region.
                territory_region = territory.region

                # Automatically use the territory's region.
                cleaned["region"] = territory_region

                # If a region was manually selected,
                # it must match the territory's region.
                if region and region.id != territory_region.id:
                    self.add_error(
                        "region",
                        "The selected region must match the territory's region."
                    )

                # Supervisor must belong to the same region.
                if supervisor:
                    supervisor_profile = getattr(
                        supervisor,
                        "sales_rep_profile",
                        None
                    )

                    if not supervisor_profile:
                        self.add_error(
                            "supervisor",
                            "The selected supervisor does not have a sales profile."
                        )
                    elif supervisor_profile.region_id != territory_region.id:
                        self.add_error(
                            "supervisor",
                            "The supervisor must be assigned to the same region as the rep's territory."
                        )

        return cleaned

    def clean_department(self):
        return "SALES"
    


class DriverProfileForm(forms.ModelForm):
    class Meta:
        model = DriverProfile

        fields = [
            "status",
            "notes",
        ]

        widgets = {
            "status": forms.Select(attrs={
                "class": "form-select",
            }),

            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Internal notes...",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["notes"].required = False