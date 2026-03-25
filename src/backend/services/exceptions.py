"""Service-layer exceptions."""


class NotFoundError(Exception):
    """Raised when a requested resource does not exist."""


class ValidationError(Exception):
    """Raised when a request violates service-layer validation rules."""
