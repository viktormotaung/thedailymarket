from celery import shared_task

from tasks.models import Ticket
from profiles.models import Department

from communications.services.email import (
    send_new_ticket_email,
)
from tasks.models import Task
from communications.services.email import send_new_task_email


@shared_task
def notify_department_new_ticket(ticket_id):

    try:
        ticket = Ticket.objects.get(pk=ticket_id)
        print("Ticket found:", ticket.id)

        department = Department.objects.filter(
            name__iexact=ticket.get_department_display()
        ).first()

        print("Department:", department)

        if not department:
            print(
                f"No Department found. Ticket department={ticket.department}"
            )
            return

        print("Department email:", department.email)

        if not department.email:
            print("NO EMAIL ADDRESS")
            return

        send_new_ticket_email(
            ticket,
            department.email,
        )

        print("EMAIL FUNCTION CALLED")

    except Exception as e:
        print(
            f"Ticket notification error: {e}"
        )




def notify_new_task(task_id):

    try:

        task = Task.objects.get(pk=task_id)

        # User assignment takes precedence
        if (
            task.assigned_to
            and task.assigned_to.email
        ):

            send_new_task_email(
                task,
                task.assigned_to.email,
            )

            return

        # Otherwise notify department
        department = Department.objects.filter(
            name__iexact=task.get_department_display()
        ).first()

        if (
            department
            and department.email
        ):

            send_new_task_email(
                task,
                department.email,
            )

    except Exception as e:

        print(
            f"Task notification error: {e}"
        )



