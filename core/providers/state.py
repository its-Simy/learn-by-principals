from enum import StrEnum


class ProviderState(StrEnum):
    """Health states, ordered from healthy to unusable."""

    AVAILABLE = "AVAILABLE"
    LIMITED = "LIMITED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    BROKEN = "BROKEN"
    DISABLED = "DISABLED"
