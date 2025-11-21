# tasks/admin.py
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Task, TaskComment


# --- Filters ---
class OverdueFilter(admin.SimpleListFilter):
    title = "Overdue"
    parameter_name = "overdue"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Overdue"),
            ("no", "Not overdue"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            now = timezone.now()
            return queryset.filter(
                due_at__lt=now,
                status__in=[Task.Status.PENDING, Task.Status.IN_PROGRESS, Task.Status.BLOCKED],
            )
        if self.value() == "no":
            now = timezone.now()
            return queryset.exclude(
                due_at__lt=now,
                status__in=[Task.Status.PENDING, Task.Status.IN_PROGRESS, Task.Status.BLOCKED],
            )
        return queryset


# --- Inlines ---
class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    fields = ("author", "body", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("author",)


# --- Admin ---
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    inlines = [TaskCommentInline]

    # Display
    list_display = (
        "id",
        "title",
        "status",
        "priority",
        "department",
        "assigned_to",
        "due_badge",
        "related_link",
        "created_at",
    )
    list_display_links = ("title",)

    # Quick edit in list view
    list_editable = ("status", "priority", "department", "assigned_to")
    ordering = ("-created_at",)

    # Filters & search
    list_filter = (
        "status",
        "priority",
        "department",
        "assigned_to",
        OverdueFilter,
        "created_at",
        "due_at",
    )
    search_fields = ("title", "description")
    date_hierarchy = "created_at"

    # Forms
    autocomplete_fields = ("assigned_to", "created_by")
    readonly_fields = ("created_at", "updated_at", "completed_at", "related_link_readonly")
    fieldsets = (
        ("Task", {
            "fields": (
                "title",
                "description",
                ("status", "priority", "department"),
            )
        }),
        ("Ownership", {
            "fields": (("created_by", "assigned_to"),)
        }),
        ("Timing", {
            "fields": (("due_at", "completed_at"),)
        }),
        ("Relation", {
            "description": "Links this task to any object in the system.",
            "fields": ("content_type", "object_id", "related_link_readonly"),
        }),
        ("Audit", {
            "classes": ("collapse",),
            "fields": (("created_at", "updated_at"),),
        }),
    )

    # --- Custom display helpers ---

    @admin.display(description="Due", ordering="due_at")
    def due_badge(self, obj: Task):
        if not obj.due_at:
            return format_html('<span style="opacity:.6">—</span>')
        if obj.is_overdue:
            return format_html('<span style="color:#b42318;font-weight:600;">{} (overdue)</span>', obj.due_at.strftime("%Y-%m-%d %H:%M"))
        return obj.due_at.strftime("%Y-%m-%d %H:%M")

    @admin.display(description="Related", ordering="object_id")
    def related_link(self, obj: Task):
        if not obj.related_object:
            return format_html('<span style="opacity:.6">—</span>')
        url = self._related_admin_url(obj)
        label = f"{obj.content_type.app_label}.{obj.content_type.model} #{obj.object_id}"
        if url:
            return format_html('<a href="{}">{}</a>', url, label)
        return label

    @admin.display(description="Related (readonly)")
    def related_link_readonly(self, obj: Task):
        return self.related_link(obj)

    def _related_admin_url(self, obj: Task):
        """Build admin change URL for the related object if possible."""
        try:
            ct = obj.content_type
            if not ct or not obj.object_id:
                return None
            return reverse(f"admin:{ct.app_label}_{ct.model}_change", args=[obj.object_id])
        except Exception:
            return None

    # --- Actions ---
    actions = ["action_mark_done", "action_mark_in_progress", "action_mark_blocked", "action_mark_canceled"]

    @admin.action(description="Mark selected tasks as Done")
    def action_mark_done(self, request, queryset):
        count = queryset.update(status=Task.Status.DONE, completed_at=timezone.now())
        self.message_user(request, f"{count} task(s) marked as Done.")

    @admin.action(description="Mark selected tasks as In progress")
    def action_mark_in_progress(self, request, queryset):
        count = queryset.update(status=Task.Status.IN_PROGRESS, completed_at=None)
        self.message_user(request, f"{count} task(s) marked as In progress.")

    @admin.action(description="Mark selected tasks as Blocked")
    def action_mark_blocked(self, request, queryset):
        count = queryset.update(status=Task.Status.BLOCKED)
        self.message_user(request, f"{count} task(s) marked as Blocked.")

    @admin.action(description="Mark selected tasks as Canceled")
    def action_mark_canceled(self, request, queryset):
        count = queryset.update(status=Task.Status.CANCELED, completed_at=None)
        self.message_user(request, f"{count} task(s) marked as Canceled.")


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "author", "created_at")
    list_filter = ("author", "created_at")
    search_fields = ("body",)
    autocomplete_fields = ("task", "author")
    readonly_fields = ("created_at",)
