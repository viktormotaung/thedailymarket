from django import forms

from clients.models import Client
from profiles.models import SalesOperator

from .models import (
    Ticket,
    TicketComment,
)


class TicketCreateForm(forms.ModelForm):

    class Meta:
        model = Ticket

        fields = [
            "title",
            "description",
            "priority",
            "department",
            "ticket_type",
            "requester_name",
            "requester_email",
            "requester_phone",
            "client",
            "sales_operator",
        ]

        widgets = {

            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ticket title",
                }
            ),

            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": "Describe the issue/request...",
                }
            ),

            "priority": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "department": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "ticket_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "requester_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Requester name",
                }
            ),

            "requester_email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Requester email",
                }
            ),

            "requester_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Requester phone",
                }
            ),

            "client": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "sales_operator": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
        }

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields["client"].queryset = (
            Client.objects
            .filter(status="ACTIVE")
            .order_by("name")
        )

        self.fields["sales_operator"].queryset = (
            SalesOperator.objects
            .filter(is_active=True)
            .order_by("name")
        )

        self.fields["client"].required = False
        self.fields["sales_operator"].required = False

        self.fields["title"].required = True


class TicketCommentForm(forms.ModelForm):

    class Meta:
        model = TicketComment

        fields = [
            "body",
            "is_internal",
        ]

        widgets = {

            "body": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Write a comment...",
                }
            ),

            "is_internal": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }