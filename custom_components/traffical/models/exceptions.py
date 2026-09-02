"""API errors (HA-free)."""

from __future__ import annotations


class ApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AuthError(ApiError):
    """OTP, refresh, or authorize failed."""
