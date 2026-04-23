# tasks/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


User = settings.AUTH_USER_MODEL





class Task(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class Department(models.TextChoices):
        SUPPORT = "SUPPORT", "Support"
        ACCOUNTS = "ACCOUNTS", "Accounts"
        SALES = "SALES", "Sales"
        COMPLIANCE = "COMPLIANCE", "Compliance"
        SUPPLY_CHAIN = "SUPPLY_CHAIN", "Supply Chain"
        OPERATIONS = "OPERATIONS", "Operations"
        LOGISTICS = "LOGISTICS", "Logistics"
        FINANCE = "FINANCE", "Finance"

    class TaskType(models.TextChoices):
        GENERAL = "GENERAL", "General"
        CLIENT_REVIEW = "CLIENT_REVIEW", "Client Review"
        CLIENT_ACTIVATION = "CLIENT_ACTIVATION", "Client Activation"
        COMPLIANCE_DOCUMENT = "COMPLIANCE_DOCUMENT", "Compliance Document"
        ORDER_FOLLOW_UP = "ORDER_FOLLOW_UP", "Order Follow-up"
        DELIVERY_PREPARATION = "DELIVERY_PREPARATION", "Delivery Preparation"
        DELIVERY_CONFIRMATION = "DELIVERY_CONFIRMATION", "Delivery Confirmation"
        PAYMENT_FOLLOW_UP = "PAYMENT_FOLLOW_UP", "Payment Follow-up"
        INVOICE_REVIEW = "INVOICE_REVIEW", "Invoice Review"
        CREDIT_REVIEW = "CREDIT_REVIEW", "Credit Review"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        SYSTEM = "SYSTEM", "System"
        WORKFLOW = "WORKFLOW", "Workflow"
        CLIENT_ACTION = "CLIENT_ACTION", "Client Action"
        FOLLOW_UP = "FOLLOW_UP", "Follow-up"

    # Core
    title = models.CharField(max_length=160, db_index=True)
    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )
    department = models.CharField(
        max_length=20,
        choices=Department.choices,
        default=Department.SUPPORT,
        db_index=True,
    )
    task_type = models.CharField(
        max_length=40,
        choices=TaskType.choices,
        default=TaskType.GENERAL,
        db_index=True,
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
        db_index=True,
    )

    # Ownership
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="tasks_created",
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks_assigned",
    )
    closed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks_closed",
    )

    ticket = models.ForeignKey(
        "Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )

    # Timing
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Generic link to any related object (e.g. Client, Order, Invoice)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("content_type", "object_id")

    # Audit
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["department"]),
            models.Index(fields=["task_type"]),
            models.Index(fields=["source"]),
            models.Index(fields=["due_at"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.due_at
            and self.status in (self.Status.PENDING, self.Status.OPEN)
            and self.due_at < timezone.now()
        )

    @property
    def is_closed(self) -> bool:
        return self.status == self.Status.CLOSED

    def mark_open(self, by=None) -> None:
        self.status = self.Status.OPEN
        if not self.opened_at:
            self.opened_at = timezone.now()
        self.save(update_fields=["status", "opened_at", "updated_at"])

    def mark_done(self, by=None) -> None:
        self.status = self.Status.CLOSED
        self.completed_at = timezone.now()
        if by:
            self.closed_by = by
            self.save(update_fields=["status", "completed_at", "closed_by", "updated_at"])
        else:
            self.save(update_fields=["status", "completed_at", "updated_at"])

    def reopen(self) -> None:
        self.status = self.Status.OPEN
        self.completed_at = None
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def save(self, *args, **kwargs):
        if self.status == self.Status.OPEN and not self.opened_at:
            self.opened_at = timezone.now()

        if self.status == self.Status.CLOSED and not self.completed_at:
            self.completed_at = timezone.now()

        if self.status in (self.Status.PENDING, self.Status.OPEN) and self.completed_at:
            self.completed_at = None

        super().save(*args, **kwargs)


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_comments",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Comment by {self.author or 'Unknown'} on {self.task}"
    

class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        OPEN = "OPEN", "Open"
        PENDING = "PENDING", "Pending"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class Department(models.TextChoices):
        SUPPORT = "SUPPORT", "Support"
        ACCOUNTS = "ACCOUNTS", "Accounts"
        SALES = "SALES", "Sales"
        COMPLIANCE = "COMPLIANCE", "Compliance"
        SUPPLY_CHAIN = "SUPPLY_CHAIN", "Supply Chain"
        OPERATIONS = "OPERATIONS", "Operations"
        LOGISTICS = "LOGISTICS", "Logistics"
        FINANCE = "FINANCE", "Finance"

    class TicketType(models.TextChoices):
        GENERAL_ENQUIRY = "GENERAL_ENQUIRY", "General Enquiry"
        SALES_ENQUIRY = "SALES_ENQUIRY", "Sales Enquiry"
        CLIENT_SUPPORT = "CLIENT_SUPPORT", "Client Support"
        DELIVERY_ISSUE = "DELIVERY_ISSUE", "Delivery Issue"
        PAYMENT_ISSUE = "PAYMENT_ISSUE", "Payment Issue"
        ACCOUNT_ISSUE = "ACCOUNT_ISSUE", "Account Issue"
        SYSTEM_GLITCH = "SYSTEM_GLITCH", "System Glitch"
        COMPLAINT = "COMPLAINT", "Complaint"
        OTHER = "OTHER", "Other"

    class Source(models.TextChoices):
        WEBSITE = "WEBSITE", "Website"
        EMAIL = "EMAIL", "Email"
        PHONE = "PHONE", "Phone"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        INTERNAL = "INTERNAL", "Internal"
        SYSTEM = "SYSTEM", "System"
        WALK_IN = "WALK_IN", "Walk-in"
        OTHER = "OTHER", "Other"

    # Core
    title = models.CharField(max_length=180, db_index=True)
    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )
    department = models.CharField(
        max_length=20,
        choices=Department.choices,
        default=Department.SUPPORT,
        db_index=True,
    )
    ticket_type = models.CharField(
        max_length=30,
        choices=TicketType.choices,
        default=TicketType.GENERAL_ENQUIRY,
        db_index=True,
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.WEBSITE,
        db_index=True,
    )

    # Requester / external contact
    requester_name = models.CharField(max_length=160, blank=True)
    requester_email = models.EmailField(blank=True)
    requester_phone = models.CharField(max_length=50, blank=True)

    # Optional known client
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    # Optional creator / closer
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_created",
    )
    closed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_closed",
    )

    # Optional generic link to any object (order, invoice, payment, etc.)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("content_type", "object_id")

    # Timing
    opened_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["department"]),
            models.Index(fields=["ticket_type"]),
            models.Index(fields=["source"]),
            models.Index(fields=["client"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_closed(self):
        return self.status == self.Status.CLOSED

    def mark_open(self):
        self.status = self.Status.OPEN
        if not self.opened_at:
            self.opened_at = timezone.now()
        self.save(update_fields=["status", "opened_at", "updated_at"])

    def mark_resolved(self, by=None):
        self.status = self.Status.RESOLVED
        self.resolved_at = timezone.now()
        if by:
            self.closed_by = by
            self.save(update_fields=["status", "resolved_at", "closed_by", "updated_at"])
        else:
            self.save(update_fields=["status", "resolved_at", "updated_at"])

    def mark_closed(self, by=None):
        self.status = self.Status.CLOSED
        self.closed_at = timezone.now()
        if by:
            self.closed_by = by
            self.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
        else:
            self.save(update_fields=["status", "closed_at", "updated_at"])

    def reopen(self):
        self.status = self.Status.OPEN
        self.resolved_at = None
        self.closed_at = None
        if not self.opened_at:
            self.opened_at = timezone.now()
        self.save(update_fields=["status", "resolved_at", "closed_at", "opened_at", "updated_at"])

    def save(self, *args, **kwargs):
        if self.status == self.Status.OPEN and not self.opened_at:
            self.opened_at = timezone.now()

        if self.status == self.Status.RESOLVED and not self.resolved_at:
            self.resolved_at = timezone.now()

        if self.status == self.Status.CLOSED and not self.closed_at:
            self.closed_at = timezone.now()

        if self.status in (self.Status.NEW, self.Status.OPEN, self.Status.PENDING):
            if self.resolved_at:
                self.resolved_at = None
            if self.closed_at:
                self.closed_at = None

        super().save(*args, **kwargs)


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_comments",
    )
    body = models.TextField()
    is_internal = models.BooleanField(
        default=True,
        help_text="Internal note vs external/customer-facing comment.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment on {self.ticket} by {self.author or 'Unknown'}"  




from django.core.exceptions import ValidationError

class Notification(models.Model):
    class NotificationType(models.TextChoices):
        TASK = "TASK", "Task"
        TICKET = "TICKET", "Ticket"

    class Scope(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        DEPARTMENT = "DEPARTMENT", "Department"

    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        db_index=True,
    )

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
        db_index=True,
    )

    department = models.CharField(
        max_length=20,
        choices=Task.Department.choices,
        null=True,
        blank=True,
        db_index=True,
    )

    notification_type = models.CharField(
        max_length=10,
        choices=NotificationType.choices,
        db_index=True,
    )

    is_opened = models.BooleanField(default=False, db_index=True)
    opened_at = models.DateTimeField(null=True, blank=True)

    opened_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opened_notifications",
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = GenericForeignKey("content_type", "object_id")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["scope", "is_opened"]),
            models.Index(fields=["recipient", "is_opened"]),
            models.Index(fields=["department", "is_opened"]),
        ]

    def __str__(self):
        if self.scope == self.Scope.INDIVIDUAL:
            return f"{self.recipient} - {self.notification_type}"
        return f"{self.department} - {self.notification_type}"

    def clean(self):
        if self.scope == self.Scope.INDIVIDUAL:
            if not self.recipient:
                raise ValidationError("Individual notifications must have a recipient.")
            if self.department:
                raise ValidationError("Individual notifications must not have a department.")

        if self.scope == self.Scope.DEPARTMENT:
            if not self.department:
                raise ValidationError("Department notifications must have a department.")
            if self.recipient:
                raise ValidationError("Department notifications must not have a recipient.")

    def mark_opened(self, user):
        if self.is_opened:
            return

        if self.scope == self.Scope.INDIVIDUAL:
            if user != self.recipient:
                return

        if self.scope == self.Scope.DEPARTMENT:
            staff = getattr(user, "staff_profile", None)
            if not staff:
                return
            if staff.status != "active":
                return
            if staff.department != self.department:
                return

        self.is_opened = True
        self.opened_at = timezone.now()
        self.opened_by = user
        self.save(update_fields=["is_opened", "opened_at", "opened_by"])

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

        