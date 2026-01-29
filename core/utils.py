from datetime import date, timedelta
from typing import Optional


def is_business_day(check_date: date) -> bool:
    """
    Check if a date is a business day (not weekend or holiday).

    Args:
        check_date: Date to check

    Returns:
        True if business day, False otherwise
    """
    # Avoid circular import by importing here
    from .models import NonWorkingDay

    # Check if weekend (Saturday=5, Sunday=6)
    if check_date.weekday() in [5, 6]:
        return False

    # Check if holiday
    return not NonWorkingDay.objects.filter(
        date=check_date,
        is_active=True
    ).exists()


def next_business_day(from_date: date, skip_current: bool = False) -> date:
    """
    Get the next business day from a given date.

    Args:
        from_date: Starting date
        skip_current: If True, start checking from the next day

    Returns:
        Next business day
    """
    print(f"Calculating next business day from: {from_date}, skip_current={skip_current}")
    current = from_date + timedelta(days=1) if skip_current else from_date
    print(f"Finding next business day starting from: {current}")
    while not is_business_day(current):
        print(f"{current} is not a business day, checking next day.")
        current += timedelta(days=1)

    return current


def adjust_to_business_day(target_date: date) -> date:
    """
    Adjust a date to the next business day if it falls on a weekend/holiday.

    Args:
        target_date: Date to adjust

    Returns:
        Same date if business day, otherwise next business day
    """
    if is_business_day(target_date):
        return target_date
    return next_business_day(target_date, skip_current=True)
