"""Service-layer exceptions translated by API routes."""


class NotFoundError(Exception):
    """Raised when a requested entity does not exist."""


class ValidationError(Exception):
    """Raised when service input violates business rules."""
