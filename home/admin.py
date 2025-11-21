from django.contrib import admin
from .models import SupplierLead

@admin.register(SupplierLead)
class SupplierLeadAdmin(admin.ModelAdmin):
    list_display = ("business_name", "full_name", "product_type", "weekly_capacity", "location", "created_at", "status")
    search_fields = ("business_name", "full_name", "email", "phone", "location")
    list_filter = ("product_type", "status", "created_at")
