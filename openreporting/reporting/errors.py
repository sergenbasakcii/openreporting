"""Report pipeline errors (shared by service, delivery and assets)."""

from ..domain import DomainError


class ReportError(DomainError):
    pass


class MailSetupError(Exception):
    """Connection failed before any message delivery command was attempted."""
