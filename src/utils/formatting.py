"""Output formatting utilities."""


def format_currency(amount: float | int | None, include_cents: bool = False) -> str:
    """Format a number as USD currency."""
    if amount is None:
        return "N/A"
    if include_cents:
        return f"${amount:,.2f}"
    return f"${amount:,.0f}"


def format_duration(days: int | float | None) -> str:
    """Format a duration in days as a human-readable string."""
    if days is None:
        return "N/A"
    days = int(days)
    if days < 30:
        return f"{days} days"
    months = days / 30.44
    if months < 12:
        return f"{months:.1f} months"
    years = months / 12
    remaining_months = months % 12
    if remaining_months < 0.5:
        return f"{int(years)} years"
    return f"{int(years)} years, {int(remaining_months)} months"


def format_percent(value: float | None, decimals: int = 1) -> str:
    """Format a float as a percentage string."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}%"


def format_change(value: float | None, decimals: int = 1) -> str:
    """Format a change value with a + or - prefix."""
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def truncate(text: str, max_length: int = 100) -> str:
    """Truncate text to a maximum length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
