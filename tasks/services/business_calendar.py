from datetime import datetime, timedelta

from django.utils import timezone

from tasks.models import BusinessDay, PublicHoliday


def is_public_holiday(dt):
    return PublicHoliday.objects.filter(
        date=dt.date()
    ).exists()


def get_business_day(dt):
    return BusinessDay.objects.filter(
        day=dt.weekday(),
        is_open=True,
    ).first()


def is_business_day(dt):
    return (
        get_business_day(dt) is not None
        and not is_public_holiday(dt)
    )


def next_business_start(dt):
    """
    Move forward to the next business opening time.
    """

    current = dt

    while True:

        business_day = get_business_day(current)

        if business_day and not is_public_holiday(current):

            opens = datetime.combine(
                current.date(),
                business_day.opens_at,
            )

            if timezone.is_naive(opens):
                opens = timezone.make_aware(opens)

            if current <= opens:
                return opens

            closes = datetime.combine(
                current.date(),
                business_day.closes_at,
            )

            if timezone.is_naive(closes):
                closes = timezone.make_aware(closes)

            if current < closes:
                return current

        # move to next day midnight
        current = (
            current + timedelta(days=1)
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )


def add_working_minutes(start_dt, minutes):
    """
    Add working minutes while respecting:
    - business days
    - opening hours
    - weekends
    - public holidays
    """

    current = next_business_start(start_dt)

    remaining = int(minutes)

    while remaining > 0:

        business_day = get_business_day(current)

        closes = datetime.combine(
            current.date(),
            business_day.closes_at,
        )

        if timezone.is_naive(closes):
            closes = timezone.make_aware(closes)

        available_minutes = int(
            (closes - current).total_seconds() / 60
        )

        if remaining <= available_minutes:
            return current + timedelta(minutes=remaining)

        remaining -= available_minutes

        current = next_business_start(
            current + timedelta(days=1)
        )

    return current


def calculate_sla_due(priority, created_at=None):

    if created_at is None:
        created_at = timezone.now()

    sla_minutes = {
        "LOW": 240,
        "MEDIUM": 120,
        "HIGH": 60,
        "URGENT": 30,
    }

    return add_working_minutes(
        created_at,
        sla_minutes.get(priority, 120)
    )

