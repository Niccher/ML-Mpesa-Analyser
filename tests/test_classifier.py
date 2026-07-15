import pytest

from app.models.schemas import FinanceCategory
from app.services.classifier import SenderClassifier


@pytest.mark.asyncio
async def test_known_sender_mpesa():
    result = await SenderClassifier.classify(
        "MPESA",
        ["You have received Ksh 1,000.00 from John"],
    )
    assert result.is_finance is True
    assert result.confidence >= 0.9
    assert result.category == FinanceCategory.mobile_money


@pytest.mark.asyncio
async def test_known_sender_kcb():
    result = await SenderClassifier.classify(
        "KCB",
        ["Ksh 5,000 CR from M-PESA. Balance: Ksh 25,000"],
    )
    assert result.is_finance is True
    assert result.confidence >= 0.9
    assert result.category == FinanceCategory.bank


@pytest.mark.asyncio
async def test_known_sender_tala():
    result = await SenderClassifier.classify(
        "TALA",
        ["Your loan of Ksh 3,000 has been disbursed to your M-PESA"],
    )
    assert result.is_finance is True
    assert result.category == FinanceCategory.fintech


@pytest.mark.asyncio
async def test_unknown_sender_no_content():
    result = await SenderClassifier.classify(
        "UNKNOWN_SENDER",
        [],
    )
    assert result.is_finance is False
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_non_finance_sender():
    result = await SenderClassifier.classify(
        "PIZZA_INN",
        ["Your order of large pizza is confirmed. ETA 30 min"],
    )
    # No match in known list, LLM not called for test without mock
    # Falls through to LLM call which raises, returning non-finance
    assert result.is_finance is False
