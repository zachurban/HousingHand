"""Date manipulation utilities for pipeline timeline analysis."""

from datetime import date, datetime, timedelta


def calculate_duration_days(start: date | None, end: date | None) -> int | None:
    """Calculate duration in days between two dates."""
    if start is None or end is None:
        return None
    return (end - start).days


def months_between(start: date, end: date) -> float:
    """Calculate approximate months between two dates."""
    days = (end - start).days
    return round(days / 30.44, 1)


def date_to_quarter(d: date) -> str:
    """Convert a date to a quarter string like '2025-Q3'."""
    quarter = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{quarter}"


def parse_timeframe(timeframe: str) -> tuple[date, date]:
    """Parse a timeframe string into a date range.

    Supported formats:
        - 'last_N_months' (e.g., 'last_24_months')
        - 'last_N_years' (e.g., 'last_2_years')
        - 'YYYY-MM-DD:YYYY-MM-DD' (explicit range)
        - 'YYYY' (full year)
    """
    today = date.today()

    if timeframe.startswith("last_"):
        parts = timeframe.split("_")
        n = int(parts[1])
        unit = parts[2]
        if unit == "months":
            start = today - timedelta(days=n * 30)
        elif unit == "years":
            start = today - timedelta(days=n * 365)
        else:
            raise ValueError(f"Unknown timeframe unit: {unit}")
        return (start, today)

    if ":" in timeframe:
        start_str, end_str = timeframe.split(":")
        return (
            datetime.strptime(start_str, "%Y-%m-%d").date(),
            datetime.strptime(end_str, "%Y-%m-%d").date(),
        )

    if len(timeframe) == 4 and timeframe.isdigit():
        year = int(timeframe)
        return (date(year, 1, 1), date(year, 12, 31))

    raise ValueError(f"Cannot parse timeframe: {timeframe}")


def days_to_months(days: int | float) -> float:
    """Convert days to months (approximate)."""
    return round(days / 30.44, 1)


def quarters_ahead(n: int) -> list[str]:
    """Return the next N quarter strings from today."""
    today = date.today()
    result = []
    current = today
    for _ in range(n):
        result.append(date_to_quarter(current))
        month = current.month + 3
        year = current.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        current = date(year, month, 1)
    return result
