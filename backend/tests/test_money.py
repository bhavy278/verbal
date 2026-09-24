from verbal.money import Money, sum_money
from verbal.errors import CurrencyMismatchError
import pytest


def test_add_and_multiply():
    assert Money.of(1599, "USD").multiply(3).amount == 4797
    assert (Money.of(1000, "USD") + Money.of(250, "USD")).amount == 1250
    assert (Money.of(1000, "USD") - Money.of(250, "USD")).amount == 750


def test_currency_mismatch():
    with pytest.raises(CurrencyMismatchError):
        Money.of(100, "USD") + Money.of(100, "EUR")


def test_tax_rounds_half_up_integer():
    # 4697 * 825bps = 387.5025 -> round half up -> 388
    assert Money.of(4697, "USD").tax(825).amount == 388
    assert Money.of(0, "USD").tax(825).amount == 0


def test_format():
    assert Money.of(1599, "USD").format() == "$15.99"
    assert Money.of(199, "USD").format() == "$1.99"
    assert Money.of(0, "USD").format() == "$0.00"


def test_sum_money():
    assert sum_money([Money.of(100, "USD"), Money.of(250, "USD")], "USD").amount == 350


def test_no_float_multiply():
    with pytest.raises(TypeError):
        Money.of(100, "USD").multiply(1.5)  # type: ignore[arg-type]
