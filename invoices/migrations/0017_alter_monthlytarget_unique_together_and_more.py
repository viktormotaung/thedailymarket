from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        (
            "invoices",
            "0016_alter_commissionentry_rep_rate_and_more",
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name="monthlytarget",
                    name="area",
                ),
                migrations.AlterUniqueTogether(
                    name="monthlytarget",
                    unique_together={
                        ("month", "year", "territory"),
                    },
                ),
            ],
        ),
    ]