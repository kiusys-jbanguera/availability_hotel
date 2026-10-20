"""Jerarquia de excepciones de proveedor traducida a status en BaseProvider."""

import logging

from availability_hotel.models import ProviderStatus


class ProviderError(Exception):
    status: ProviderStatus = ProviderStatus.HTTP_ERROR
    log_level: int = logging.WARNING

    def __init__(
        self,
        message: str = "",
        error_code: str | None = None,
        log_level: int | None = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        self.error_code = error_code
        if log_level is not None:
            self.log_level = log_level


class ProviderTimeout(ProviderError):
    status = ProviderStatus.TIMEOUT


class ProviderRateLimited(ProviderError):
    status = ProviderStatus.RATE_LIMITED

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message, error_code="RATE_LIMITED")
        self.retry_after = retry_after


class ProviderBusinessError(ProviderError):
    status = ProviderStatus.BUSINESS_ERROR


class ProviderHttpError(ProviderError):
    status = ProviderStatus.HTTP_ERROR


class ProviderParseError(ProviderError):
    status = ProviderStatus.PARSE_ERROR


class ProviderNoAvailability(Exception):
    """Respuesta valida sin disponibilidad: status ok sin ofertas (HU001 RF-08)."""
