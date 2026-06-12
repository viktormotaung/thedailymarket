from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import Department, StaffProfile


@receiver(m2m_changed, sender=Department.members.through)
def sync_department_members(sender, instance, action, pk_set, **kwargs):
    """
    Keep StaffProfile.departments in sync with Department.members.
    """

    if action == "post_add":

        for user_id in pk_set:

            try:
                staff = StaffProfile.objects.get(user_id=user_id)

                staff.departments.add(instance)

                if not staff.primary_department:
                    staff.primary_department = instance
                    staff.save(update_fields=["primary_department"])

            except StaffProfile.DoesNotExist:
                pass

    elif action == "post_remove":

        for user_id in pk_set:

            try:
                staff = StaffProfile.objects.get(user_id=user_id)

                staff.departments.remove(instance)

                if staff.primary_department_id == instance.id:
                    replacement = staff.departments.first()

                    staff.primary_department = replacement
                    staff.save(update_fields=["primary_department"])

            except StaffProfile.DoesNotExist:
                pass