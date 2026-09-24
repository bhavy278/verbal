"""Domain and infrastructure error types.

Every recoverable domain failure carries a stable machine ``code`` so callers
(CLI, API, voice orchestrator) can react deterministically. The voice model is
never handed free-form error prose it might treat as an instruction.
"""

from __future__ import annotations


class VerbalError(Exception):
    """Base class for all Verbal errors."""

    code = "verbal_error"
    http_status = 400

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def as_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


class DomainError(VerbalError):
    """Business-rule violation (safe to surface to a caller)."""

    code = "domain_error"
    http_status = 422


class CurrencyMismatchError(DomainError):
    code = "currency_mismatch"


class CatalogError(VerbalError):
    code = "catalog_error"


class ItemNotFoundError(DomainError):
    code = "item_not_found"


class VariantNotFoundError(DomainError):
    code = "variant_not_found"


class ModifierNotFoundError(DomainError):
    code = "modifier_not_found"


class InvalidModifierComboError(DomainError):
    code = "invalid_modifier_combo"


class ItemUnavailableError(DomainError):
    code = "item_unavailable"


class LineNotFoundError(DomainError):
    code = "line_not_found"


class OrderNotFoundError(DomainError):
    code = "order_not_found"
    http_status = 404


class InvalidQuantityError(DomainError):
    code = "invalid_quantity"


class EmptyOrderError(DomainError):
    code = "empty_order"


class NoQuoteError(DomainError):
    code = "no_quote"


class StaleQuoteError(DomainError):
    """Quote no longer matches current revision — caller must re-quote."""

    code = "stale_quote"


class ExpiredQuoteError(DomainError):
    code = "expired_quote"


class NoConfirmationError(DomainError):
    code = "no_confirmation"


class StaleConfirmationError(DomainError):
    """Order edited after confirmation was issued — must re-confirm."""

    code = "stale_confirmation"


class ConfirmationMismatchError(DomainError):
    code = "confirmation_mismatch"


class NotConfirmedError(DomainError):
    code = "not_confirmed"


class InvalidStateError(DomainError):
    code = "invalid_state"
