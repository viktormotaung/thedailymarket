from django import forms

from .models import JobApplication

class JobApplicationForm(forms.ModelForm):

    OPTIONAL_FIELDS = [
        "race",
        "gender",
        "year_matriculated",
        "qualifications",
        "current_employment_status",
        "leadership_experience",
        "introduction_video_link",
    ]

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():

            # =====================================================
            # REQUIRED LOGIC
            # =====================================================

            field.required = (
                field_name not in self.OPTIONAL_FIELDS
            )

            # =====================================================
            # CSS CLASSES
            # =====================================================

            if isinstance(
                field.widget,
                forms.CheckboxInput
            ):

                css_classes = [
                    "form-check-input"
                ]

            elif isinstance(
                field.widget,
                forms.Select
            ):

                css_classes = [
                    "form-select"
                ]

            else:

                css_classes = [
                    "form-control"
                ]

            # =====================================================
            # VALIDATION STYLING
            # =====================================================

            if self.is_bound:

                if field_name in self.errors:

                    css_classes.append(
                        "is-invalid"
                    )

                else:

                    css_classes.append(
                        "is-valid"
                    )

            field.widget.attrs["class"] = (
                " ".join(css_classes)
            )

    class Meta:

        model = JobApplication

        fields = [

            # =====================================================
            # TERRITORY
            # =====================================================

            "territory",

            # =====================================================
            # BASIC PERSONAL INFORMATION
            # =====================================================

            "first_name",
            "surname",
            "age",
            "race",
            "gender",
            "phone_number",
            "whatsapp_number",
            "email",
            "current_location",
            "year_matriculated",
            "qualifications",
            "current_employment_status",
            "availability_to_start",

            # =====================================================
            # TRANSPORT & RESOURCES
            # =====================================================

            "has_drivers_license",
            "has_vehicle_access",
            "has_smartphone",

            # =====================================================
            # TERRITORY & COMMERCIAL THINKING
            # =====================================================

            "territory_understanding",
            "potential_client_types",
            "first_30_day_strategy",

            # =====================================================
            # SALES & PROBLEM SOLVING
            # =====================================================

            "cheaper_supplier_response",
            "client_retention_strategy",
            "target_pressure_response",

            # =====================================================
            # LEADERSHIP & ACCOUNTABILITY
            # =====================================================

            "leadership_experience",
            "unsupervised_problem_solving",
            "performance_environment_understanding",

            # =====================================================
            # STARTUP & CULTURE FIT
            # =====================================================

            "startup_interest_reason",
            "comfortable_performance_environment",
            "motivation",

            # =====================================================
            # OPTIONAL VIDEO
            # =====================================================

            "introduction_video_link",
        ]

        widgets = {

            # =====================================================
            # LONG FORM ANSWERS
            # =====================================================

            "territory_understanding": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "potential_client_types": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "first_30_day_strategy": forms.Textarea(
                attrs={
                    "rows": 5,
                }
            ),

            "cheaper_supplier_response": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "client_retention_strategy": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "target_pressure_response": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "leadership_experience": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "unsupervised_problem_solving": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "performance_environment_understanding": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "startup_interest_reason": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),

            "motivation": forms.Textarea(
                attrs={
                    "rows": 4,
                }
            ),
        }

        labels = {

            # =====================================================
            # TERRITORY
            # =====================================================

            "territory": "Which territory are you applying for?",

            # =====================================================
            # BASIC INFO
            # =====================================================

            "first_name": "First name",
            "surname": "Surname",
            "age": "Age",
            "race": "Race",
            "gender": "Gender",
            "phone_number": "Phone number",
            "whatsapp_number": "WhatsApp number",
            "email": "Email address",
            "current_location": (
                "Current suburb / township / area"
            ),
            "year_matriculated": (
                "Year matriculated"
            ),
            "qualifications": (
                "Qualifications / certificates"
            ),
            "current_employment_status": (
                "Current employment status"
            ),
            "availability_to_start": (
                "When can you start?"
            ),

            # =====================================================
            # TRANSPORT
            # =====================================================

            "has_drivers_license": (
                "Do you have a valid driver's license?"
            ),

            "has_vehicle_access": (
                "Do you have access to a vehicle?"
            ),

            "has_smartphone": (
                "Do you have access to a smartphone?"
            ),

            # =====================================================
            # COMMERCIAL THINKING
            # =====================================================

            "territory_understanding": (
                "Name trader zones, business hubs or "
                "areas within your territory where "
                "you believe The Daily Market could "
                "find clients."
            ),

            "potential_client_types": (
                "What type of businesses or traders "
                "would benefit most from "
                "The Daily Market?"
            ),

            "first_30_day_strategy": (
                "If you had to secure 10 recurring "
                "clients within 30 days, "
                "what would your approach be?"
            ),

            # =====================================================
            # SALES THINKING
            # =====================================================

            "cheaper_supplier_response": (
                "A client says another supplier "
                "is cheaper than The Daily Market. "
                "What would you do?"
            ),

            "client_retention_strategy": (
                "A client buys once and never "
                "orders again. "
                "How would you handle this?"
            ),

            "target_pressure_response": (
                "You have not reached target and "
                "only 7 days remain in the month. "
                "What would you do?"
            ),

            # =====================================================
            # LEADERSHIP
            # =====================================================

            "leadership_experience": (
                "Have you ever managed people, "
                "coordinated a group or led a project?"
            ),

            "unsupervised_problem_solving": (
                "Describe a difficult problem "
                "you solved without supervision."
            ),

            "performance_environment_understanding": (
                "What makes someone successful "
                "in a performance-based environment?"
            ),

            # =====================================================
            # STARTUP FIT
            # =====================================================

            "startup_interest_reason": (
                "Why do you want to join a growing "
                "startup business instead of a "
                "traditional company?"
            ),

            "comfortable_performance_environment": (
                "Are you comfortable working in a "
                "performance-based environment?"
            ),

            "motivation": (
                "What motivates you most?"
            ),

            # =====================================================
            # VIDEO
            # =====================================================

            "introduction_video_link": (
                "Optional introduction video link"
            ),
        }