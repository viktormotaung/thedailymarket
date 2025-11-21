from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils.timezone import localdate
from invoices.models import Invoice

class Command(BaseCommand):
    help = "Marks past-due invoices (not fully paid) as OVERDUE."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would be updated, but do not write changes.")

    def handle(self, *args, **options):
        today = localdate()
        qs = (Invoice.objects
              .filter(due_date__lt=today)
              .exclude(status__in=["paid", "overdue"])
              .filter(deposit_paid__lt=F("amount_due")))

        count = qs.count()
        if options["dry_run"]:
            self.stdout.write(f"[DRY RUN] Would mark {count} invoice(s) overdue.")
            return

        updated = qs.update(status="overdue")
        self.stdout.write(self.style.SUCCESS(f"Marked {updated} invoice(s) as OVERDUE."))
