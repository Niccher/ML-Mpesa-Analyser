from app.models.schemas import (
    Direction,
    FinanceCategory,
    MessageExtraction,
    ModeARequest,
    ModeAResponse,
    SenderClassification,
    TransactionType,
)


def test_sender_classification():
    sc = SenderClassification(
        sender="MPESA",
        is_finance=True,
        confidence=0.99,
        category=FinanceCategory.mobile_money,
        reasoning="Test",
    )
    assert sc.sender == "MPESA"
    assert sc.is_finance is True
    assert sc.confidence == 0.99


def test_message_extraction():
    me = MessageExtraction(
        body="Received Ksh 1000 from John",
        is_transactional=True,
        amount_changed=1000.0,
        direction=Direction.received,
        counterparty="John",
        transaction_type=TransactionType.transfer,
    )
    assert me.is_transactional is True
    assert me.amount_changed == 1000.0
    assert me.direction == Direction.received
    assert me.counterparty == "John"


def test_mode_a_request():
    payload = {
        "messages": {
            "MPESA": [
                "You have received Ksh 1,000.00 from John Doe on 15/7/2026",
                "You have sent Ksh 500.00 to Jane Smith on 14/7/2026",
            ],
            "KCB": [
                "Ksh 5,000.00 CR from M-PESA. Account balance: Ksh 25,000.00",
            ],
        }
    }
    req = ModeARequest(**payload)
    assert "MPESA" in req.messages
    assert len(req.messages["MPESA"]) == 2


def test_classification_deserialize():
    raw = {
        "sender": "MPESA",
        "is_finance": True,
        "confidence": 0.99,
        "category": "Mobile Money",
        "reasoning": "MPESA is Safaricom's mobile money service.",
    }
    sc = SenderClassification(**raw)
    assert sc.category == FinanceCategory.mobile_money
    assert sc.is_finance is True
