"""Money — integer minor units + currency. No floats for money, ever.

All arithmetic is exact integer arithmetic on minor units (e.g. cents). The
currency is carried alongside so cross-currency mistakes fail loudly.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from .errors import CurrencyMismatchError

_SYMBOLS = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "INR": "\u20b9"}
_DECIMALS = {"USD": 2, "EUR": 2, "GBP": 2, "INR": 2, "JPY": 0}


class Money(BaseModel):
    """An exact monetary amount expressed in minor units of ``currency``."""

    model_config = {"frozen": True}

    amount: int  # minor units (integer)
    currency: str

    @field_validator("currency")
    @classmethod
    def _normalise_currency(cls, v: str) -> str:
        return v.upper()

    # -- constructors -------------------------------------------------
    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(amount=0, currency=currency)

    @classmethod
    def of(cls, amount: int, currency: str) -> "Money":
        return cls(amount=amount, currency=currency)

    # -- guards -------------------------------------------------------
    def _same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"Cannot combine {self.currency} with {other.currency}"
            )

    # -- arithmetic ---------------------------------------------------
    def add(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def multiply(self, factor: int) -> "Money":
        if not isinstance(factor, int):
            raise TypeError("Money can only be multiplied by an integer factor")
        return Money(amount=self.amount * factor, currency=self.currency)

    def tax(self, rate_bps: int) -> "Money":
        """Return tax at ``rate_bps`` basis points, rounded half-up (integer)."""
        taxed = (self.amount * rate_bps + 5000) // 10000
        return Money(amount=taxed, currency=self.currency)

    def __add__(self, other: "Money") -> "Money":
        return self.add(other)

    def __sub__(self, other: "Money") -> "Money":
        return self.subtract(other)

    def __mul__(self, factor: int) -> "Money":
        return self.multiply(factor)

    # -- formatting ---------------------------------------------------
    @property
    def decimals(self) -> int:
        return _DECIMALS.get(self.currency, 2)

    @property
    def major_str(self) -> str:
        d = self.decimals
        if d == 0:
            return str(self.amount)
        sign = "-" if self.amount < 0 else ""
        whole, frac = divmod(abs(self.amount), 10**d)
        return f"{sign}{whole}.{frac:0{d}d}"

    def format(self) -> str:
        symbol = _SYMBOLS.get(self.currency, "")
        if symbol:
            return f"{symbol}{self.major_str}"
        return f"{self.major_str} {self.currency}"

    def __str__(self) -> str:
        return self.format()


def sum_money(items: list[Money], currency: str) -> Money:
    total = Money.zero(currency)
    for m in items:
        total = total.add(m)
    return total
