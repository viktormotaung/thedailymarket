# tasks/views.py
from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from datetime import datetime, time, timedelta

from django.contrib import messages  # ← add this
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from profiles.models import StaffProfile

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from tasks.models import Notification
from .models import Task, Ticket, TicketComment
from django.urls import reverse
from django.utils.timesince import timesince
from django.contrib.contenttypes.models import ContentType




# --- Auth helpers ---
def staff_check(user):
    return user.is_authenticated and user.is_staff


staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")


# --- Utils ---
def _parse_date_local(date_str: str):
    """Parse YYYY-MM-DD to aware start/end of that day in local TZ."""
    try:
        d = datetime.fromisoformat(date_str).date()
        start_naive = datetime.combine(d, time.min)
        end_naive = datetime.combine(d, time.max)
        return timezone.make_aware(start_naive), timezone.make_aware(end_naive)
    except Exception:
        return None, None


@login_required
@staff_required
def tasks(request):
    """
    Staff task board with filters:
    - q: search in title/description
    - status: PENDING|OPEN|CLOSED
    - priority: LOW|MEDIUM|HIGH|URGENT
    - department: Department choices
    - mine=1: only tasks assigned to me
    - period: 7|14|30|60 (days back, by created_at)
    - due_from/due_to: YYYY-MM-DD range on due_at
    - order: created_at|-created_at|due_at|-due_at|priority|-priority|status|-status|department|-department|title|-title
    - page, per_page
    """
    qs = Task.objects.select_related("assigned_to", "content_type")

    # --- Query params ---
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    department = (request.GET.get("department") or "").strip()
    mine = request.GET.get("mine") == "1"
    period = (request.GET.get("period") or "").strip()
    due_from = (request.GET.get("due_from") or "").strip()
    due_to = (request.GET.get("due_to") or "").strip()

    # Search
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    # Choice filters
    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if department:
        qs = qs.filter(department=department)
    if mine:
        qs = qs.filter(assigned_to=request.user)

    # Period (created_at)
    if period.isdigit() and int(period) in (7, 14, 30, 60):
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=int(period)))

    # Due range (due_at)
    if due_from:
        start_from, _ = _parse_date_local(due_from)
        if start_from:
            qs = qs.filter(due_at__gte=start_from)
    if due_to:
        _, end_to = _parse_date_local(due_to)
        if end_to:
            qs = qs.filter(due_at__lte=end_to)

    # Ordering
    allowed_order = {
        "created_at", "-created_at",
        "due_at", "-due_at",
        "priority", "-priority",
        "status", "-status",
        "department", "-department",
        "title", "-title",
    }
    order = request.GET.get("order") or "-created_at"
    if order not in allowed_order:
        order = "-created_at"
    qs = qs.order_by(order)

    # Stats (global, not filtered)
    now = timezone.now()
    base = Task.objects.all()
    stats = {
        "total": base.count(),
        "mine": base.filter(assigned_to=request.user).count(),
        "open": base.filter(status__in=[Task.Status.PENDING, Task.Status.OPEN]).count(),
        "closed": base.filter(status=Task.Status.CLOSED).count(),
        "overdue": base.filter(
            due_at__lt=now,
            status__in=[Task.Status.PENDING, Task.Status.OPEN],
        ).count(),
        "by_status": dict(base.values_list("status").annotate(c=Count("id"))),
        "by_department": dict(base.values_list("department").annotate(c=Count("id"))),
    }

    # Pagination
    per_page_qs = request.GET.get("per_page")
    try:
        per_page = max(1, min(int(per_page_qs or 25), 200))
    except Exception:
        per_page = 25

    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # Optional flash messages
    success_message = request.GET.get("ok") or ""
    error_message = request.GET.get("err") or ""

    ctx = {
        "page_obj": page_obj,
        "object_list": page_obj.object_list,
        "stats": stats,
        "filters": {
            "q": q,
            "status": status,
            "priority": priority,
            "department": department,
            "mine": mine,
            "period": period,
            "due_from": due_from,
            "due_to": due_to,
            "order": order,
            "per_page": per_page,
        },
        "choices": {
            "status": Task.Status.choices,
            "priority": Task.Priority.choices,
            "department": Task.Department.choices,
        },
        "ui": {
            "period_options": [7, 14, 30, 60],
            "order_options": [
                "created_at", "-created_at",
                "due_at", "-due_at",
                "priority", "-priority",
                "status", "-status",
                "department", "-department",
                "title", "-title",
            ],
            "per_page_options": [10, 25, 50, 100, 200],
        },
        "success_message": success_message,
        "error_message": error_message,
    }
    return render(request, "tasks/tasks.html", ctx)


# --- Optional quick actions (wire to buttons/links if needed) ---
@login_required
@staff_required
def task_close(request, pk: int):
    task = Task.objects.filter(pk=pk).first()
    if not task:
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Task+not+found")
    if not (request.user.is_staff or request.user == task.assigned_to or request.user == task.created_by):
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Not+authorized")
    task.status = Task.Status.CLOSED
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?ok=Task+closed")


@login_required
@staff_required
def task_reopen(request, pk: int):
    task = Task.objects.filter(pk=pk).first()
    if not task:
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Task+not+found")
    if not (request.user.is_staff or request.user == task.assigned_to or request.user == task.created_by):
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Not+authorized")
    task.status = Task.Status.OPEN
    task.completed_at = None
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?ok=Task+reopened")


@login_required
@staff_required
def task_view(request, pk):
    task = get_object_or_404(Task, pk=pk)

    # Mark linked task notification as opened when the task is viewed
    task_content_type = ContentType.objects.get_for_model(Task)

    linked_notifications = Notification.objects.filter(
        notification_type=Notification.NotificationType.TASK,
        content_type=task_content_type,
        object_id=task.pk,
        is_opened=False,
    )

    for notification in linked_notifications:
        if notification.scope == Notification.Scope.INDIVIDUAL:
            if notification.recipient == request.user:
                notification.mark_opened(request.user)

        elif notification.scope == Notification.Scope.DEPARTMENT:
            staff = getattr(request.user, "staff_profile", None)
            if staff and staff.status == "active" and staff.department == notification.department:
                notification.mark_opened(request.user)

    # Load staff for dropdown
    staff_members = StaffProfile.objects.filter(status="active").select_related("user")

    # Load comments
    try:
        comments_qs = task.comments.order_by("-created_at")
    except Exception:
        comments_qs = []

    # Related URL
    related_url = getattr(
        getattr(task, "related_object", None),
        "get_absolute_url",
        lambda: None
    )()

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        # Authorization
        is_authorized = (
            request.user.is_staff
            or request.user == getattr(task, "assigned_to", None)
            or request.user == getattr(task, "created_by", None)
        )

        if not is_authorized:
            messages.error(request, "Not authorized to update this task.")
            return redirect(request.path)

        # Handle status updates
        if action in ["close", "pending", "reopen"]:
            if action == "close":
                task.status = Task.Status.CLOSED
                task.completed_at = timezone.now()

            elif action == "pending":
                task.status = Task.Status.PENDING
                task.completed_at = None

            elif action == "reopen":
                task.status = Task.Status.OPEN
                task.completed_at = None

            task.save(update_fields=["status", "completed_at", "updated_at"])
            messages.success(request, f"Task {action}d.")
            return redirect(request.path)

        # Handle assigning staff
        elif action == "assign":
            staff_id = request.POST.get("assigned_to")

            try:
                staff_profile = StaffProfile.objects.get(pk=staff_id)
                task.assigned_to = staff_profile.user
                task.save(update_fields=["assigned_to", "updated_at"])
                messages.success(
                    request,
                    f"Task assigned to {staff_profile.user.get_full_name() or staff_profile.user.username}."
                )

            except StaffProfile.DoesNotExist:
                messages.error(request, "Selected staff member does not exist.")

            return redirect(request.path)

        # Handle adding comments
        elif action == "add_comment":
            body = (request.POST.get("comment") or "").strip()

            if not body:
                messages.error(request, "Comment cannot be empty.")
                return redirect(request.path)

            try:
                from .models import TaskComment

                TaskComment.objects.create(
                    task=task,
                    body=body,
                    author=request.user if request.user.is_authenticated else None,
                )

                messages.success(request, "Comment added.")

            except Exception:
                messages.error(request, "Comments are not enabled.")

            return redirect(request.path)

        # Delete task
        elif action == "delete":
            if not (
                request.user.is_staff
                or request.user == getattr(task, "created_by", None)
            ):
                messages.error(request, "Not authorized to delete this task.")
                return redirect(request.path)

            task.delete()
            messages.success(request, "Task deleted.")
            return redirect("tasks")

        else:
            messages.error(request, "Unknown action.")
            return redirect(request.path)

    return render(
        request,
        "tasks/task_view.html",
        {
            "task": task,
            "comments": comments_qs,
            "related_url": related_url,
            "staff_members": staff_members,
        },
    )



@login_required
def notification_count(request):
    user = request.user

    individual_qs = Notification.objects.filter(
        scope=Notification.Scope.INDIVIDUAL,
        recipient=user,
    )

    staff = getattr(user, "staff_profile", None)
    department_qs = Notification.objects.none()

    if staff and staff.status == "active" and staff.department:
        department_qs = Notification.objects.filter(
            scope=Notification.Scope.DEPARTMENT,
            department=staff.department,
        )

    all_qs = (individual_qs | department_qs).distinct()

    unread_count = all_qs.filter(is_opened=False).count()

    ticket_count = all_qs.filter(
        notification_type=Notification.NotificationType.TICKET,
        is_opened=False,
    ).count()

    task_count = all_qs.filter(
        notification_type=Notification.NotificationType.TASK,
        is_opened=False,
    ).count()

    return JsonResponse({
        "unread_count": unread_count,
        "ticket_count": ticket_count,
        "task_count": task_count,
    })

@login_required
@staff_required
def tickets(request):
    qs = Ticket.objects.select_related(
        "client",
        "created_by",
        "closed_by",
        "content_type",
    )

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    department = (request.GET.get("department") or "").strip()
    ticket_type = (request.GET.get("ticket_type") or "").strip()
    source = (request.GET.get("source") or "").strip()

    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(requester_name__icontains=q)
            | Q(requester_email__icontains=q)
            | Q(requester_phone__icontains=q)
            | Q(client__name__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    if priority:
        qs = qs.filter(priority=priority)

    if department:
        qs = qs.filter(department=department)

    if ticket_type:
        qs = qs.filter(ticket_type=ticket_type)

    if source:
        qs = qs.filter(source=source)

    qs = qs.order_by("-created_at")

    stats_base = Ticket.objects.all()

    stats = {
        "total": stats_base.count(),
        "new": stats_base.filter(status=Ticket.Status.NEW).count(),
        "open": stats_base.filter(status=Ticket.Status.OPEN).count(),
        "pending": stats_base.filter(status=Ticket.Status.PENDING).count(),
        "resolved": stats_base.filter(status=Ticket.Status.RESOLVED).count(),
        "closed": stats_base.filter(status=Ticket.Status.CLOSED).count(),
    }

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(
        request.GET.get("page") or 1
    )

    return render(
        request,
        "tasks/tickets.html",
        {
            "page_obj": page_obj,
            "object_list": page_obj.object_list,
            "stats": stats,
            "filters": {
                "q": q,
                "status": status,
                "priority": priority,
                "department": department,
                "ticket_type": ticket_type,
                "source": source,
            },
            "choices": {
                "status": Ticket.Status.choices,
                "priority": Ticket.Priority.choices,
                "department": Ticket.Department.choices,
                "ticket_type": Ticket.TicketType.choices,
                "source": Ticket.Source.choices,
            },
        },
    )


@login_required
@staff_required
def ticket_view(request, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related(
            "client",
            "created_by",
            "closed_by",
            "content_type",
        ),
        pk=pk,
    )

    ticket_content_type = ContentType.objects.get_for_model(Ticket)

    linked_notifications = Notification.objects.filter(
        notification_type=Notification.NotificationType.TICKET,
        content_type=ticket_content_type,
        object_id=ticket.pk,
        is_opened=False,
    )

    for notification in linked_notifications:
        if notification.scope == Notification.Scope.INDIVIDUAL:
            if notification.recipient == request.user:
                notification.mark_opened(request.user)

        elif notification.scope == Notification.Scope.DEPARTMENT:
            staff = getattr(request.user, "staff_profile", None)

            if (
                staff
                and staff.status == "active"
                and staff.department == notification.department
            ):
                notification.mark_opened(request.user)

    comments_qs = ticket.comments.select_related("author").order_by("-created_at")
    linked_tasks = ticket.tasks.select_related("assigned_to").order_by("-created_at")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "open":
            ticket.mark_open()
            messages.success(request, "Ticket marked as open.")
            return redirect(request.path)

        elif action == "pending":
            ticket.status = Ticket.Status.PENDING
            ticket.save(update_fields=["status", "updated_at"])
            messages.success(request, "Ticket marked as pending.")
            return redirect(request.path)

        elif action == "resolve":
            ticket.mark_resolved(by=request.user)
            messages.success(request, "Ticket resolved.")
            return redirect(request.path)

        elif action == "close":
            ticket.mark_closed(by=request.user)
            messages.success(request, "Ticket closed.")
            return redirect(request.path)

        elif action == "reopen":
            ticket.reopen()
            messages.success(request, "Ticket reopened.")
            return redirect(request.path)

        elif action == "add_comment":
            body = (request.POST.get("comment") or "").strip()
            is_internal = request.POST.get("is_internal") == "on"

            if not body:
                messages.error(request, "Comment cannot be empty.")
                return redirect(request.path)

            TicketComment.objects.create(
                ticket=ticket,
                author=request.user,
                body=body,
                is_internal=is_internal,
            )

            messages.success(request, "Comment added.")
            return redirect(request.path)

        else:
            messages.error(request, "Unknown action.")
            return redirect(request.path)

    return render(
        request,
        "tasks/ticket_view.html",
        {
            "ticket": ticket,
            "comments": comments_qs,
            "linked_tasks": linked_tasks,
        },
    )


