from django.urls import path
from . import views

urlpatterns = [
    path("tasks/", views.tasks, name="tasks"),
    path("tasks/<int:pk>/", views.task_view, name="task_view"),

    path("tickets/", views.tickets, name="tickets"),
    path("tickets/<int:pk>/", views.ticket_view, name="ticket_view"),

    path("notifications/count/", views.notification_count, name="notification-count"),
]
