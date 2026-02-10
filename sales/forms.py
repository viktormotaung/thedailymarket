from django import forms
from .models import SalesJobApplication


class SalesJobApplicationForm(forms.ModelForm):
    """
    Sales Job Application Form
    Styled to match internal Daily Market system forms
    All fields are required unless explicitly stated otherwise
    """

    OPTIONAL_FIELDS = [
        "current_job",
        "leadership_skills_description",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():

            # -------------------------
            # REQUIRED LOGIC
            # -------------------------
            field.required = field_name not in self.OPTIONAL_FIELDS

            # -------------------------
            # BASE CSS CLASSES
            # -------------------------
            if isinstance(field.widget, forms.CheckboxInput):
                css_classes = ["form-check-input"]
            elif isinstance(field.widget, forms.Select):
                css_classes = ["form-select"]
            else:
                css_classes = ["form-control"]

            # -------------------------
            # VALIDATION FEEDBACK
            # -------------------------
            if self.is_bound:
                if field_name in self.errors:
                    css_classes.append("is-invalid")
                else:
                    css_classes.append("is-valid")

            field.widget.attrs["class"] = " ".join(css_classes)

    class Meta:
        model = SalesJobApplication

        fields = [
            # -------------------------
            # Personal info
            # -------------------------
            "first_name",
            "last_name",
            "email",
            "date_of_birth",
            "nationality",
            "province",
            "suburb",
            "town_or_city",
            "where_grew_up",

            # -------------------------
            # Sales background
            # -------------------------
            "sales_experience_summary",
            "previous_workplaces",
            "responsibilities",
            "lessons_learned",

            # -------------------------
            # Sales thinking
            # -------------------------
            "client_identification_strategy",
            "pitching_strategy",
            "conversion_strategy",
            "client_management_strategy",

            # -------------------------
            # Resources
            # -------------------------
            "resources_needed",
            "has_drivers_license",
            "has_vehicle_access",
            "has_laptop_or_tablet",

            # -------------------------
            # Work style & fit
            # -------------------------
            "can_work_in_team",
            "leadership_skills_description",
            "comfortable_township_clients",
            "comfortable_suburban_clients",
            "comfortable_remote_work",
            "comfortable_startup_environment",

            # -------------------------
            # Status
            # -------------------------
            "current_job",
            "availability_to_start",
        ]

        widgets = {
            # -------------------------
            # Dates
            # -------------------------
            "date_of_birth": forms.DateInput(
                attrs={"type": "date"}
            ),

            # -------------------------
            # Long-form answers
            # -------------------------
            "sales_experience_summary": forms.Textarea(attrs={"rows": 4}),
            "previous_workplaces": forms.Textarea(attrs={"rows": 3}),
            "responsibilities": forms.Textarea(attrs={"rows": 4}),
            "lessons_learned": forms.Textarea(attrs={"rows": 3}),

            "client_identification_strategy": forms.Textarea(attrs={"rows": 4}),
            "pitching_strategy": forms.Textarea(attrs={"rows": 4}),
            "conversion_strategy": forms.Textarea(attrs={"rows": 4}),
            "client_management_strategy": forms.Textarea(attrs={"rows": 4}),

            "resources_needed": forms.Textarea(attrs={"rows": 3}),
            "leadership_skills_description": forms.Textarea(attrs={"rows": 3}),
        }

        labels = {
            # -------------------------
            # Personal
            # -------------------------
            "email": "Email address",
            "where_grew_up": "Where did you grow up?",

            # -------------------------
            # Sales background
            # -------------------------
            "sales_experience_summary": "Describe your sales experience",
            "previous_workplaces": "Where have you worked before?",
            "responsibilities": "What responsibilities did you have?",
            "lessons_learned": "What did you learn from these roles?",

            # -------------------------
            # Sales thinking
            # -------------------------
            "client_identification_strategy": "How would you identify potential clients?",
            "pitching_strategy": "How would you pitch FMCG products?",
            "conversion_strategy": "How do you convert prospects into clients?",
            "client_management_strategy": "How would you manage and retain clients?",

            # -------------------------
            # Resources
            # -------------------------
            "resources_needed": "What resources do you need to perform well?",
            "leadership_skills_description": "Describe your leadership skills or experience",

            "has_drivers_license": "Do you have a valid driver’s license?",
            "has_vehicle_access": "Do you have access to a vehicle?",
            "has_laptop_or_tablet": "Do you have access to a laptop or tablet?",

            # -------------------------
            # Work style
            # -------------------------
            "comfortable_township_clients": "Comfortable working with township-based clients",
            "comfortable_suburban_clients": "Comfortable working with suburban-based clients",
            "comfortable_remote_work": "Comfortable working remotely",
            "comfortable_startup_environment": "Comfortable working in a startup environment",

            # -------------------------
            # Status
            # -------------------------
            "availability_to_start": "How soon can you start?",
            "current_job": "Current job (if any)",
        }
