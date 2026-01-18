from django import forms
from .models import DeliveryRun
from django.contrib.auth import get_user_model

User = get_user_model()


class DeliveryRunAssignmentForm(forms.ModelForm):
    class Meta:
        model = DeliveryRun
        fields = ["driver", "vehicle"]

    driver = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        empty_label="— Select driver —",
    )

    vehicle = forms.ModelChoiceField(
        queryset=None,  # set in __init__
        required=False,
        empty_label="— Select vehicle —",
    )

    def __init__(self, *args, **kwargs):
        vehicles_qs = kwargs.pop("vehicles_qs", None)
        super().__init__(*args, **kwargs)

        if vehicles_qs is not None:
            self.fields["vehicle"].queryset = vehicles_qs
