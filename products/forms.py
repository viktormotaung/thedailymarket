# products/forms.py
from decimal import Decimal
from django import forms
from django.forms import inlineformset_factory
from products.models import ProductPricing, Product, ProductVariant
from suppliers.models import Supplier


class ProductPricingForm(forms.ModelForm):
    class Meta:
        model = ProductPricing
        fields = [
            "supplier",
            "supplier_price_excl",
            "supplier_vat_percent",

            "wholesale_margin_percent",
            "wholesale_vat_percent",

            "retail_margin_percent",
            "retail_vat_percent",

            "is_primary",         # <-- NEW: show primary toggle
            "skip_variant_sync",  # <-- NEW: show the tick to keep variants unchanged
            "is_active",
        ]
        widgets = {
            "supplier": forms.Select(attrs={"class": "form-select"}),

            "supplier_price_excl": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "supplier_vat_percent": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}
            ),

            "wholesale_margin_percent": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "-100", "max": "1000"}
            ),
            "wholesale_vat_percent": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}
            ),

            "retail_margin_percent": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "-100", "max": "1000"}
            ),
            "retail_vat_percent": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}
            ),

            "is_primary": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "skip_variant_sync": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "is_primary": "Make this the primary pricing row",
            "skip_variant_sync": "Don’t update variants from this save",
        }
        help_texts = {
            "is_primary": "If ticked, this row sets the Product’s base wholesale/retail (EXCL) prices.",
            "skip_variant_sync": "Tick to update the Product base prices only; existing variant prices stay as-is.",
        }

    def __init__(self, *args, **kwargs):
        """
        Limit supplier choices to those not already linked to this product.
        When editing an existing row, keep its current supplier selectable.
        """
        product = kwargs.pop("product", None)
        super().__init__(*args, **kwargs)

        qs = Supplier.objects.all().order_by("name")
        if product is not None:
            used_ids = ProductPricing.objects.filter(product=product)\
                         .values_list("supplier_id", flat=True)

            # On edit, allow the current supplier to remain selectable
            if self.instance and self.instance.pk and self.instance.supplier_id:
                used_ids = [pk for pk in used_ids if pk != self.instance.supplier_id]

            qs = qs.exclude(id__in=list(used_ids))
        self.fields["supplier"].queryset = qs

        # Friendly defaults (model defaults still apply on save)
        self.fields["supplier_vat_percent"].initial = (
            self.instance.supplier_vat_percent if self.instance and self.instance.supplier_vat_percent is not None
            else Decimal("15.00")
        )
        self.fields["wholesale_margin_percent"].initial = (
            getattr(self.instance, "wholesale_margin_percent", None) if self.instance and self.instance.pk
            else Decimal("15.00")
        )
        self.fields["wholesale_vat_percent"].initial = (
            getattr(self.instance, "wholesale_vat_percent", None) if self.instance and self.instance.pk
            else Decimal("15.00")
        )
        self.fields["retail_margin_percent"].initial = (
            getattr(self.instance, "retail_margin_percent", None) if self.instance and self.instance.pk
            else Decimal("15.00")
        )
        self.fields["retail_vat_percent"].initial = (
            getattr(self.instance, "retail_vat_percent", None) if self.instance and self.instance.pk
            else Decimal("0.00")
        )


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "category", "sku", "image", "uom"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "uom": forms.Select(attrs={"class": "form-select"}),
        }


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = [
            "pack_size", "uom", "name", "sku", "image",
            "wholesale_price_override", "retail_price_override", "scales_with_pack"
        ]
        widgets = {
            "pack_size": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "uom": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "sku": forms.TextInput(attrs={"class": "form-control"}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "wholesale_price_override": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "retail_price_override": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "scales_with_pack": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


# Inline formset: variants under a product
ProductVariantFormSet = inlineformset_factory(
    parent_model=Product,
    model=ProductVariant,
    form=ProductVariantForm,
    extra=1,            # show one empty form initially
    can_delete=True,    # allow removing existing ones in edit
)
