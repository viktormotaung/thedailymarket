# tasks/admin.py
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from profiles.models import Department
from .models import (
    Task,
    TaskComment,
    Ticket,
    TicketComment,
    Notification, 
    BusinessDay,
    PublicHoliday,
)



class TaskOverdueFilter(admin.SimpleListFilter):
    title = "Overdue"
    parameter_name = "overdue"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Overdue"),
            ("no", "Not overdue"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()

        if self.value() == "yes":
            return queryset.filter(
                expected_resolution_at__lt=now,
                status__in=[Task.Status.PENDING, Task.Status.OPEN],
            )

        if self.value() == "no":
            return queryset.exclude(
                expected_resolution_at__lt=now,
                status__in=[Task.Status.PENDING, Task.Status.OPEN],
            )

        return queryset


class NotificationOpenedFilter(admin.SimpleListFilter):
    title = "Opened"
    parameter_name = "opened"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Opened"),
            ("no", "Not opened"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(is_opened=True)
        if self.value() == "no":
            return queryset.filter(is_opened=False)
        return queryset


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    fields = ("author", "body", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("author",)


class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0
    fields = ("author", "body", "is_internal", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("author",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    inlines = [TaskCommentInline]

    list_display = (
        "id",
        "title",
        "status",
        "priority",
        "department",
        "task_type",
        "assigned_to",
        "sla_badge",
        "due_badge",
        "ticket_link",
        "created_at",
    )

    list_display_links = ("title",)

    list_editable = (
        "status",
        "priority",
        "department",
        "task_type",
        "assigned_to",
    )

    ordering = ("-created_at",)

    list_filter = (
        "status",
        "priority",
        "department",
        "task_type",
        "source",
        "assigned_to",
        TaskOverdueFilter,
        "created_at",
        "due_at",
        "expected_resolution_at",
        "opened_at",
        "completed_at",
    )

    search_fields = (
        "title",
        "description",
        "ticket__title",
    )

    date_hierarchy = "created_at"

    autocomplete_fields = (
        "department",
        "created_by",
        "assigned_to",
        "closed_by",
        "ticket",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "opened_at",
        "completed_at",
        "expected_resolution_at",
        "related_link_readonly",
        "ticket_link_readonly",
        "is_overdue_display",
    )

    fieldsets = (
        ("Task", {
            "fields": (
                "title",
                "description",
                ("status", "priority"),
                ("department", "task_type", "source"),
            )
        }),
        ("Ownership", {
            "fields": (
                ("created_by", "assigned_to", "closed_by"),
            )
        }),
        ("Ticket Link", {
            "fields": (
                "ticket",
                "ticket_link_readonly",
            )
        }),
        ("Timing", {
            "fields": (
                ("due_at", "expected_resolution_at"),
                ("opened_at", "completed_at"),
                "is_overdue_display",
            )
        }),
        ("Relation", {
            "fields": (
                "content_type",
                "object_id",
                "related_link_readonly",
            ),
        }),
        ("Audit", {
            "classes": ("collapse",),
            "fields": (
                ("created_at", "updated_at"),
            ),
        }),
    )

    actions = (
        "action_mark_pending",
        "action_mark_open",
        "action_mark_closed",
    )

    @admin.display(description="SLA")
    def sla_badge(self, obj):

        if not obj.expected_resolution_at:
            return "-"

        if obj.is_closed:
            return format_html(
                '<span style="color:#18794e;font-weight:600;">Closed</span>'
            )

        if obj.is_sla_overdue:
            return format_html(
                '<span style="color:#b42318;font-weight:600;">Overdue</span>'
            )

        return format_html(
            '<span style="color:#18794e;font-weight:600;">On time</span>'
        )

    @admin.display(description="Due", ordering="due_at")
    def due_badge(self, obj: Task):
        if not obj.due_at:
            return format_html('<span style="opacity:.6;">—</span>')

        if obj.is_due:
            return format_html(
                '<span style="color:#b42318;font-weight:600;">{} (overdue)</span>',
                obj.due_at.strftime("%Y-%m-%d %H:%M"),
            )

        return obj.due_at.strftime("%Y-%m-%d %H:%M")

    @admin.display(description="Ticket", ordering="ticket")
    def ticket_link(self, obj: Task):
        if not obj.ticket_id:
            return format_html('<span style="opacity:.6;">—</span>')

        try:
            url = reverse("admin:tasks_ticket_change", args=[obj.ticket_id])
            return format_html('<a href="{}">{}</a>', url, obj.ticket.title)
        except Exception:
            return obj.ticket.title

    @admin.display(description="Ticket (readonly)")
    def ticket_link_readonly(self, obj: Task):
        return self.ticket_link(obj)

    @admin.display(description="Related", ordering="object_id")
    def related_link(self, obj: Task):
        if not obj.related_object:
            return format_html('<span style="opacity:.6;">—</span>')

        url = self._related_admin_url(obj)
        label = f"{obj.content_type.app_label}.{obj.content_type.model} #{obj.object_id}"

        if url:
            return format_html('<a href="{}">{}</a>', url, label)

        return label

    @admin.display(description="Related (readonly)")
    def related_link_readonly(self, obj: Task):
        return self.related_link(obj)

    @admin.display(description="Overdue")
    def is_overdue_display(self, obj: Task):
        if obj.is_due:
            return format_html('<span style="color:#b42318;font-weight:600;">Yes</span>')
        return format_html('<span style="color:#18794e;font-weight:600;">No</span>')

    def _related_admin_url(self, obj: Task):
        try:
            ct = obj.content_type
            if not ct or not obj.object_id:
                return None
            return reverse(f"admin:{ct.app_label}_{ct.model}_change", args=[obj.object_id])
        except Exception:
            return None

    @admin.action(description="Mark selected tasks as Pending")
    def action_mark_pending(self, request, queryset):
        count = queryset.update(
            status=Task.Status.PENDING,
            completed_at=None,
        )
        self.message_user(request, f"{count} task(s) marked as Pending.")

    @admin.action(description="Mark selected tasks as Open")
    def action_mark_open(self, request, queryset):
        now = timezone.now()
        count = queryset.update(
            status=Task.Status.OPEN,
            completed_at=None,
            opened_at=now,
        )
        self.message_user(request, f"{count} task(s) marked as Open.")

    @admin.action(description="Mark selected tasks as Closed")
    def action_mark_closed(self, request, queryset):
        now = timezone.now()
        count = queryset.update(
            status=Task.Status.CLOSED,
            completed_at=now,
        )
        self.message_user(request, f"{count} task(s) marked as Closed.")


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "author", "created_at")
    list_filter = ("author", "created_at")
    search_fields = ("body", "task__title")
    autocomplete_fields = ("task", "author")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    inlines = [TicketCommentInline]

    list_display = (
        "id",
        "title",
        "status",
        "priority",
        "department",
        "ticket_type",
        "source",
        "client",
        "sales_operator",
        "requester_name",
        "sla_badge",
        "tasks_count",
        "related_link",
        "created_at",
    )

    list_display_links = ("title",)

    list_editable = (
        "status",
        "priority",
        "department",
        "ticket_type",
    )

    ordering = ("-created_at",)

    list_filter = (
        "status",
        "priority",
        "department",
        "ticket_type",
        "source",
        "client",
        "sales_operator",
        "created_at",
        "expected_resolution_at",
        "opened_at",
        "resolved_at",
        "closed_at",
    )

    search_fields = (
        "title",
        "description",
        "requester_name",
        "requester_email",
        "requester_phone",
        "client__name",
        "client__organization",
        "sales_operator__name",
    )

    date_hierarchy = "created_at"

    autocomplete_fields = (
        "department",
        "client",
        "sales_operator",
        "created_by",
        "closed_by",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "opened_at",
        "resolved_at",
        "closed_at",
        "expected_resolution_at",
        "tasks_links_readonly",
        "related_link_readonly",
    )

    fieldsets = (
        ("Ticket", {
            "fields": (
                "title",
                "description",
                ("status", "priority"),
                ("department", "ticket_type", "source"),
            )
        }),
        ("Requester", {
            "fields": (
                ("requester_name", "requester_email", "requester_phone"),
                ("client", "sales_operator"),
            )
        }),
        ("Workflow", {
            "fields": (
                ("created_by", "closed_by"),
                "tasks_links_readonly",
            )
        }),
        ("Relation", {
            "fields": (
                "content_type",
                "object_id",
                "related_link_readonly",
            )
        }),
        ("Timing", {
            "fields": (
                "expected_resolution_at",
                ("opened_at", "resolved_at", "closed_at"),
            )
        }),
        ("Audit", {
            "classes": ("collapse",),
            "fields": (
                ("created_at", "updated_at"),
            ),
        }),
    )

    actions = (
        "action_mark_new",
        "action_mark_open",
        "action_mark_pending",
        "action_mark_resolved",
        "action_mark_closed",
    )

    @admin.display(description="SLA")
    def sla_badge(self, obj):

        if not obj.expected_resolution_at:
            return "-"

        if obj.is_closed:
            return format_html(
                '<span style="color:#18794e;font-weight:600;">Closed</span>'
            )

        if obj.is_sla_overdue:
            return format_html(
                '<span style="color:#b42318;font-weight:600;">Overdue</span>'
            )

        return format_html(
            '<span style="color:#18794e;font-weight:600;">On time</span>'
        )

    @admin.display(description="Tasks")
    def tasks_count(self, obj: Ticket):
        return obj.tasks.count()

    @admin.display(description="Tasks (readonly)")
    def tasks_links_readonly(self, obj: Ticket):
        if not obj.pk:
            return format_html('<span style="opacity:.6;">Save first to see linked tasks.</span>')

        tasks = obj.tasks.all()[:10]

        if not tasks:
            return format_html('<span style="opacity:.6;">No linked tasks.</span>')

        links = []

        for task in tasks:
            try:
                url = reverse("admin:tasks_task_change", args=[task.pk])
                links.append(f'<a href="{url}">{task.title}</a>')
            except Exception:
                links.append(task.title)

        content = "<br>".join(links)

        if obj.tasks.count() > 10:
            content += "<br><span style='opacity:.7;'>…more tasks linked</span>"

        return format_html(content)

    @admin.display(description="Related", ordering="object_id")
    def related_link(self, obj: Ticket):
        if not obj.related_object:
            return format_html('<span style="opacity:.6;">—</span>')

        url = self._related_admin_url(obj)
        label = f"{obj.content_type.app_label}.{obj.content_type.model} #{obj.object_id}"

        if url:
            return format_html('<a href="{}">{}</a>', url, label)

        return label

    @admin.display(description="Related (readonly)")
    def related_link_readonly(self, obj: Ticket):
        return self.related_link(obj)

    def _related_admin_url(self, obj: Ticket):
        try:
            ct = obj.content_type
            if not ct or not obj.object_id:
                return None
            return reverse(f"admin:{ct.app_label}_{ct.model}_change", args=[obj.object_id])
        except Exception:
            return None

    @admin.action(description="Mark selected tickets as New")
    def action_mark_new(self, request, queryset):
        count = queryset.update(
            status=Ticket.Status.NEW,
            resolved_at=None,
            closed_at=None,
        )
        self.message_user(request, f"{count} ticket(s) marked as New.")

    @admin.action(description="Mark selected tickets as Open")
    def action_mark_open(self, request, queryset):
        now = timezone.now()
        count = queryset.update(
            status=Ticket.Status.OPEN,
            opened_at=now,
            resolved_at=None,
            closed_at=None,
        )
        self.message_user(request, f"{count} ticket(s) marked as Open.")

    @admin.action(description="Mark selected tickets as Pending")
    def action_mark_pending(self, request, queryset):
        count = queryset.update(
            status=Ticket.Status.PENDING,
            resolved_at=None,
            closed_at=None,
        )
        self.message_user(request, f"{count} ticket(s) marked as Pending.")

    @admin.action(description="Mark selected tickets as Resolved")
    def action_mark_resolved(self, request, queryset):
        now = timezone.now()
        count = queryset.update(
            status=Ticket.Status.RESOLVED,
            resolved_at=now,
        )
        self.message_user(request, f"{count} ticket(s) marked as Resolved.")

    @admin.action(description="Mark selected tickets as Closed")
    def action_mark_closed(self, request, queryset):
        now = timezone.now()
        count = queryset.update(
            status=Ticket.Status.CLOSED,
            closed_at=now,
        )
        self.message_user(request, f"{count} ticket(s) marked as Closed.")


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket",
        "author",
        "is_internal",
        "created_at",
    )

    list_filter = (
        "is_internal",
        "author",
        "created_at",
    )

    search_fields = (
        "body",
        "ticket__title",
        "ticket__client__name",
        "ticket__client__organization",
        "ticket__sales_operator__name",
    )

    autocomplete_fields = (
        "ticket",
        "author",
    )

    readonly_fields = (
        "created_at",
    )

    ordering = (
        "-created_at",
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "scope",
        "notification_type",
        "recipient",
        "department",
        "is_opened",
        "opened_by",
        "opened_at",
        "related_link",
        "created_at",
    )

    list_editable = (
        "is_opened",
    )

    ordering = ("-created_at",)

    list_filter = (
        "scope",
        "notification_type",
        "department",
        "is_opened",
        NotificationOpenedFilter,
        "created_at",
        "opened_at",
    )

    search_fields = (
        "recipient__username",
        "recipient__first_name",
        "recipient__last_name",
        "opened_by__username",
    )

    autocomplete_fields = (
        "recipient",
        "department",
        "opened_by",
    )

    readonly_fields = (
        "created_at",
        "opened_at",
        "related_link_readonly",
    )

    fieldsets = (
        ("Notification", {
            "fields": (
                ("scope", "notification_type"),
                ("recipient", "department"),
            )
        }),
        ("Open State", {
            "fields": (
                ("is_opened", "opened_at", "opened_by"),
            )
        }),
        ("Relation", {
            "fields": (
                "content_type",
                "object_id",
                "related_link_readonly",
            )
        }),
        ("Audit", {
            "classes": ("collapse",),
            "fields": (
                "created_at",
            ),
        }),
    )

    actions = (
        "action_mark_opened",
        "action_mark_unopened",
    )

    @admin.display(description="Related", ordering="object_id")
    def related_link(self, obj: Notification):
        if not obj.related_object:
            return format_html('<span style="opacity:.6;">—</span>')

        url = self._related_admin_url(obj)
        label = f"{obj.content_type.app_label}.{obj.content_type.model} #{obj.object_id}"

        if url:
            return format_html('<a href="{}">{}</a>', url, label)

        return label

    @admin.display(description="Related (readonly)")
    def related_link_readonly(self, obj: Notification):
        return self.related_link(obj)

    def _related_admin_url(self, obj: Notification):
        try:
            ct = obj.content_type
            if not ct or not obj.object_id:
                return None
            return reverse(f"admin:{ct.app_label}_{ct.model}_change", args=[obj.object_id])
        except Exception:
            return None

    @admin.action(description="Mark selected notifications as opened")
    def action_mark_opened(self, request, queryset):
        now = timezone.now()
        count = queryset.update(
            is_opened=True,
            opened_at=now,
            opened_by=request.user,
        )
        self.message_user(request, f"{count} notification(s) marked as opened.")

    @admin.action(description="Mark selected notifications as unopened")
    def action_mark_unopened(self, request, queryset):
        count = queryset.update(
            is_opened=False,
            opened_at=None,
            opened_by=None,
        )
        self.message_user(request, f"{count} notification(s) marked as unopened.")


@admin.register(BusinessDay)
class BusinessDayAdmin(admin.ModelAdmin):
    list_display = (
        "day",
        "is_open",
        "opens_at",
        "closes_at",
    )

    list_editable = (
        "is_open",
        "opens_at",
        "closes_at",
    )

    ordering = ("day",)


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "name",
    )

    ordering = ("date",)

    search_fields = (
        "name",
    )