from django.contrib.admin import AdminSite
from django.contrib import admin
from django.contrib.auth import get_user_model

User = get_user_model()


# -----------------------------
# 1. Create Dummy Admin Site
# -----------------------------
class DummyAdminSite(AdminSite):
    site_header = "Dummy Admin"
    site_title = "Dummy Admin"
    index_title = "Dummy Environment"


dummy_admin_site = DummyAdminSite(name="dummy_admin")


# -----------------------------
# 2. Force ALL admin actions to use dummy DB
# -----------------------------
class DummyDBMixin:

    # ✅ All list views use dummy DB
    def get_queryset(self, request):
        return super().get_queryset(request).using("dummy")

    # ✅ Save to dummy DB
    def save_model(self, request, obj, form, change):
        obj.save(using="dummy")

    # ✅ Delete from dummy DB
    def delete_model(self, request, obj):
        obj.delete(using="dummy")

    # -----------------------------
    # 🔥 FK handling (FIXED PROPERLY)
    # -----------------------------
    def formfield_for_foreignkey(self, db_field, request, **kwargs):

        model = db_field.remote_field.model

        if model == User:
            kwargs["queryset"] = User.objects.using("default").all()
        else:
            kwargs["queryset"] = model.objects.using("dummy").all()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # -----------------------------
    # 🔥 M2M handling
    # -----------------------------
    def formfield_for_manytomany(self, db_field, request, **kwargs):

        model = db_field.remote_field.model

        if model == User:
            kwargs["queryset"] = User.objects.using("default").all()
        else:
            kwargs["queryset"] = model.objects.using("dummy").all()

        return super().formfield_for_manytomany(db_field, request, **kwargs)

    # -----------------------------
    # 🔥 FORM FIX (CRITICAL)
    # -----------------------------
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        for field_name, field in form.base_fields.items():
            try:
                if hasattr(field, "queryset"):

                    model = field.queryset.model

                    if model == User:
                        field.queryset = User.objects.using("default").all()
                    else:
                        field.queryset = model.objects.using("dummy").all()

            except Exception:
                pass

        return form

    # -----------------------------
    # 🔥 AUTOCOMPLETE FIX (VERY IMPORTANT)
    # -----------------------------
    def get_search_results(self, request, queryset, search_term):

        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )

        try:
            model = queryset.model

            if model == User:
                queryset = model.objects.using("default").all()
            else:
                queryset = queryset.using("dummy")

        except Exception:
            pass

        return queryset, use_distinct


# -----------------------------
# 3. Clone ALL existing admin registrations
# -----------------------------
def register_all_models_to_dummy_admin():
    for model, model_admin in admin.site._registry.items():
        try:

            # ✅ Remove filters (prevents cross-db errors)
            attrs = {
                "list_filter": (),
                "search_fields": getattr(model_admin, "search_fields", ()),
                "list_display": getattr(model_admin, "list_display", ("__str__",)),
                "ordering": getattr(model_admin, "ordering", ()),
            }

            DummyAdminClass = type(
                f"Dummy{model.__name__}Admin",
                (DummyDBMixin, model_admin.__class__),
                attrs
            )

            dummy_admin_site.register(model, DummyAdminClass)

        except Exception:
            pass


register_all_models_to_dummy_admin()