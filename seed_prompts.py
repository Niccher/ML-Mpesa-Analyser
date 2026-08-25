#!/usr/bin/env python3
"""
Seed script: push the revised Financial Analyst & Advisor prompts to the
ML service admin API so they become the active DB prompts and override the
hardcoded defaults.

Usage:
    python3 seed_prompts.py
"""
import sys
import json
import urllib.request
import urllib.error

ML_BASE = "http://localhost:9022"  # ML service internal port

# ── Updated prompts ──────────────────────────────────────────────────────────

CLASSIFY_SENDER = """You are a financial SMS classifier. Determine whether the sender of the following SMS messages is finance-related.

Finance-related senders include: banks, mobile money services (MPESA, Airtel Money, T-Kash), SACCOS, fintech lenders (Tala, Branch, Zenka), insurance companies, payment aggregators (PesaLink, eCitizen), and government revenue authorities (KRA).

Non-finance senders include: marketing/promotional numbers, social media, utilities (water/power — unless payment confirmations), ride-hailing, e-commerce order confirmations, and general service notifications that do not involve money.

Sender name: {sender}

Sample SMS messages from this sender:
{sms_messages}

Respond with valid JSON only, using this exact schema:
{
    "sender": "<sender>",
    "is_finance": true/false,
    "confidence": 0.0-1.0,
    "category": "Mobile Money" | "Bank" | "SACCO" | "Fintech" | "Insurance" | "Payments/Govt" | "Other Finance" | "Non-Finance",
    "reasoning": "brief explanation"
}
"""

EXTRACT_BATCH = """You are a Senior Financial Analyst and Personal Wealth Advisor. Parse each of the following SMS messages and extract structured financial information, cash flow trends, normality assessment, and financial advisory warnings.

For each message:
- is_transactional: true if this SMS describes a financial transaction (money movement, balance change, payment, deposit). false if it is a notification (OTP, promo, maintenance alert, general info).
- amount_before: balance before the transaction, if explicitly stated. null otherwise.
- amount_after: balance after the transaction, if explicitly stated. null otherwise.
- amount_changed: the transaction amount. null if not found or not transactional.
- direction: "sent" if money left the account, "received" if money came in, "none" if not applicable.
- fee: transaction cost, transfer fee, convenience fee, or charge. null if not stated.
- is_reversal: true if reversal, cancellation, failed transaction, or refunded transaction. false otherwise.
- is_loan: true if loan disbursement (credit/incoming cash from lending services like KCB M-Pesa, M-Shwari, Fuliza, Tala, Branch). false otherwise.
- transaction_time: any date/time mentioned. null if not present.
- counterparty: the other party. null if not present.
- transaction_reference: any reference code. null if not present.
- transaction_type: "transfer", "payment", "deposit", "withdrawal", "loan", "repayment", "salary", "fee", "interest", "refund", "other", "unknown".
- Swahili/Sheng terms: "tuma" means sent, "nitumie" means request/received, "bob" means currency amount, "kutoa" means withdraw, "nimetuma X ya Y" means X amount sent for Y payment. Examples: "Nimetuma 200 ya gas" -> amount_changed=200, direction="sent", transaction_type="payment", counterparty="gas".

/* --- FINANCIAL INTELLIGENCE ANALYSIS --- */
- category: Map to one of: "Mobile Money", "Bank Transfer", "Payments/Govt", "Airtime", "Shopping", "Food & Drink", "Transport", "Utilities", "Entertainment", "Salary", "Rent", "Savings", "Loan Repayment", "Unclassified".
- counterparty_type: Map to "merchant", "person", "utility", "bank", "lending_service", "employer", "unknown".
- is_abnormal: Set to true if the transaction exhibits abnormal features (e.g. transfer fee > 10% of amount, overdraft/loan taken, late-night gambling, potential duplicate transaction). False otherwise.
- normality_assessment: A brief explanation of the normality status (e.g., "Normal daily transport expense", "Abnormal: High carrier fee charged").
- savings_impact: "positive" (inflow), "negative" (outflow), or "neutral" (transfers between own accounts, reversals).
- advisor_insight: Provide a brief actionable advice point (e.g., "High transaction fee detected; try bundling transfers to reduce fees.", "Disbursed overdraft loan carries high interest. Clear this early to minimize fee penalties.").

Messages (index | body):
{messages_list}

Respond with a valid JSON array only. One object per message, in the same order:
[
  {
    "body": "original SMS text...",
    "is_transactional": true/false,
    "amount_before": null or number,
    "amount_after": null or number,
    "amount_changed": null or number,
    "direction": "sent" | "received" | "none",
    "fee": null or number,
    "is_reversal": true/false,
    "is_loan": true/false,
    "transaction_time": null or string,
    "counterparty": null or string,
    "transaction_reference": null or string,
    "transaction_type": "transfer" | "payment" | "deposit" | "withdrawal" | "loan" | "repayment" | "salary" | "fee" | "interest" | "refund" | "other" | "unknown",
    "category": "Mobile Money" | "Bank Transfer" | "Payments/Govt" | "Airtime" | "Shopping" | "Food & Drink" | "Transport" | "Utilities" | "Entertainment" | "Salary" | "Rent" | "Savings" | "Loan Repayment" | "Unclassified",
    "counterparty_type": "merchant" | "person" | "utility" | "bank" | "lending_service" | "employer" | "unknown",
    "is_abnormal": true/false,
    "normality_assessment": "string",
    "savings_impact": "positive" | "negative" | "neutral",
    "advisor_insight": "string"
  }
]
"""

PROMPTS = [
    {
        "key": "classify_sender",
        "title": "Financial Sender Classifier v2",
        "body": CLASSIFY_SENDER,
    },
    {
        "key": "extract_batch",
        "title": "Financial Analyst & Advisor Extractor v2",
        "body": EXTRACT_BATCH,
    },
]


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main():
    errors = []
    for p in PROMPTS:
        url = f"{ML_BASE}/admin/prompts"
        payload = {"prompt_key": p["key"], "title": p["title"], "body": p["body"]}
        print(f"→ Seeding prompt key='{p['key']}' title='{p['title']}' ...", end=" ")
        try:
            result = post_json(url, payload)
            status = result.get("status", "?")
            if status == "ok":
                print(f"✓  v{result.get('version')} created and set active.")
            else:
                print(f"✗  {result.get('message')}")
                errors.append(p["key"])
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"✗  HTTP {e.code}: {body}")
            errors.append(p["key"])
        except Exception as ex:
            print(f"✗  {ex}")
            errors.append(p["key"])

    if errors:
        print(f"\n[FAIL] Failed to seed: {errors}")
        sys.exit(1)
    else:
        print("\n[OK] All prompts seeded and active.")


if __name__ == "__main__":
    main()
