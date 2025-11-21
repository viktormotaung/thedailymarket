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

from .models import Task


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

    # Optional: load comments if you have a TaskComment model with FK "task" and related_name "comments"
    try:
        comments_qs = task.comments.order_by("-created_at")
    except Exception:
        comments_qs = []

    # Optional: build a related URL if the linked object exposes get_absolute_url()
    related_url = None
    if task.related_object:
        try:
            if hasattr(task.related_object, "get_absolute_url"):
                related_url = task.related_object.get_absolute_url()
        except Exception:
            related_url = None

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        # Basic authorization: staff OR the assignee OR the creator
        is_authorized = (
            request.user.is_staff
            or request.user == getattr(task, "assigned_to", None)
            or request.user == getattr(task, "created_by", None)
        )
        if not is_authorized:
            messages.error(request, "Not authorized to update this task.")
            return redirect(request.path)

        if action == "close":
            task.status = Task.Status.CLOSED
            task.completed_at = timezone.now()
            task.save(update_fields=["status", "completed_at", "updated_at"])
            messages.success(request, "Task closed.")
            return redirect(request.path)

        elif action == "pending":
            task.status = Task.Status.PENDING
            # keep completed_at as-is (usually None or a past value)
            task.save(update_fields=["status", "updated_at"])
            messages.success(request, "Task marked as pending.")
            return redirect(request.path)

        elif action == "reopen":
            task.status = Task.Status.OPEN
            task.completed_at = None
            task.save(update_fields=["status", "completed_at", "updated_at"])
            messages.success(request, "Task reopened.")
            return redirect(request.path)

        elif action == "add_comment":
            body = (request.POST.get("comment") or "").strip()
            if not body:
                messages.error(request, "Comment cannot be empty.")
                return redirect(request.path)

            # Only if you have a TaskComment model
            try:
                from .models import TaskComment  # adjust import if located elsewhere
                TaskComment.objects.create(
                    task=task,
                    body=body,
                    author=request.user if request.user.is_authenticated else None,
                    author_name=str(request.user) if request.user.is_authenticated else "System",
                )
                messages.success(request, "Comment added.")
            except Exception:
                messages.error(request, "Comments are not enabled.")
            return redirect(request.path)

        elif action == "delete":
            # Optional: allow only staff or creator to delete
            if not (request.user.is_staff or request.user == getattr(task, "created_by", None)):
                messages.error(request, "Not authorized to delete this task.")
                return redirect(request.path)
            task.delete()
            messages.success(request, "Task deleted.")
            return redirect("tasks")  # back to list

        else:
            messages.error(request, "Unknown action.")
            return redirect(request.path)

    # GET: render page
    return render(
        request,
        "tasks/task_view.html",
        {
            "task": task,
            "comments": comments_qs,
            "related_url": related_url,
        },
    )