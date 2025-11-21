from django.urls import path
from . import views

urlpatterns = [
    path("tasks/", views.tasks, name="tasks"),
    path("tasks/<int:pk>/", views.task_view, name="task_view"),
  
   

]
