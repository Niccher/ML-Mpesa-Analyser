CLASSIFY_SENDER_PROMPT = """You are a financial SMS classifier. Determine whether the sender of the following SMS messages is finance-related.

Finance-related senders include: banks, mobile money services (MPESA, Airtel Money, T-Kash), SACCOS, fintech lenders (Tala, Branch, Zenka), insurance companies, payment aggregators (PesaLink, eCitizen), and government revenue authorities (KRA).

Non-finance senders include: marketing/promotional numbers, social media, utilities (water/power — unless payment confirmations), ride-hailing, e-commerce order confirmations, and general service notifications that do not involve money.

Sender name: {sender}

Sample SMS messages from this sender:
{sms_messages}

Respond with valid JSON only, using this exact schema:
{{
    "sender": "{sender}",
    "is_finance": true/false,
    "confidence": 0.0-1.0,
    "category": "Mobile Money" | "Bank" | "SACCO" | "Fintech" | "Insurance" | "Payments/Govt" | "Other Finance" | "Non-Finance",
    "reasoning": "brief explanation"
}}
"""

EXTRACT_MESSAGE_PROMPT = """You are a financial data extractor. Parse the following SMS message and extract structured financial information.

Message body: {sms_body}

Instructions:
- is_transactional: true if this SMS describes a financial transaction (money movement, balance change, payment, deposit, etc.). false if it is a notification (OTP, promo, maintenance alert, account opening confirmation, general info).
- amount_before: the account balance before the transaction, if explicitly stated. null otherwise.
- amount_after: the account balance after the transaction, if explicitly stated. null otherwise.
- amount_changed: the monetary amount involved in the transaction. null if not found or not transactional.
- direction: "sent" if money left the account, "received" if money came in, "none" if not applicable.
- transaction_time: any date or time mentioned in the message. return as ISO-like string or the exact text. null if not present.
- counterparty: the other person, business, or institution on the other side of the transaction. null if not present or not transactional.
- transaction_reference: any transaction code, receipt number, or reference ID. null if not present.
- transaction_type: classify the type. one of: "transfer", "payment", "deposit", "withdrawal", "loan", "repayment", "salary", "fee", "interest", "refund", "other", "unknown".

Respond with valid JSON only, using this exact schema:
{{
    "body": "{sms_body_short}",
    "is_transactional": true/false,
    "amount_before": null or number,
    "amount_after": null or number,
    "amount_changed": null or number,
    "direction": "sent" | "received" | "none",
    "transaction_time": null or string,
    "counterparty": null or string,
    "transaction_reference": null or string,
    "transaction_type": "transfer" | "payment" | "deposit" | "withdrawal" | "loan" | "repayment" | "salary" | "fee" | "interest" | "refund" | "other" | "unknown"
}}
"""

BATCH_EXTRACT_PROMPT = """You are a financial data extractor. Parse each of the following SMS messages and extract structured financial information.

For each message, extract according to these rules:
- is_transactional: true if this SMS describes a financial transaction (money movement, balance change, payment, deposit, etc.). false if it is a notification (OTP, promo, maintenance alert, account opening confirmation, general info).
- amount_before: the account balance before the transaction, if explicitly stated. null otherwise.
- amount_after: the account balance after the transaction, if explicitly stated. null otherwise.
- amount_changed: the monetary amount involved in the transaction. null if not found or not transactional.
- direction: "sent" if money left the account, "received" if money came in, "none" if not applicable.
- transaction_time: any date or time mentioned in the message. return as ISO-like string or the exact text. null if not present.
- counterparty: the other person, business, or institution on the other side of the transaction. null if not present or not transactional.
- transaction_reference: any transaction code, receipt number, or reference ID. null if not present.
- transaction_type: "transfer", "payment", "deposit", "withdrawal", "loan", "repayment", "salary", "fee", "interest", "refund", "other", "unknown".

Messages (index | body):
{messages_list}

Respond with a valid JSON array only, one object per message in the same order. Use this exact schema per item:
{{
    "body": "original SMS text (truncated to 120 chars if long)",
    "is_transactional": true/false,
    "amount_before": null or number,
    "amount_after": null or number,
    "amount_changed": null or number,
    "direction": "sent" | "received" | "none",
    "transaction_time": null or string,
    "counterparty": null or string,
    "transaction_reference": null or string,
    "transaction_type": "transfer" | "payment" | "deposit" | "withdrawal" | "loan" | "repayment" | "salary" | "fee" | "interest" | "refund" | "other" | "unknown"
}}
"""

# Hardcoded default prompts, used when no DB version is active for a key.
# Placeholders are single-brace tokens (e.g. {sender}) — these are substituted
# via simple string replacement, so they do NOT conflict with the literal JSON
# braces used inside the prompt schema examples.
DEFAULT_CLASSIFY_SENDER = """You are a financial SMS classifier. Determine whether the sender of the following SMS messages is finance-related.

Finance-related senders include: banks, mobile money services (MPESA, Airtel Money, T-Kash), SACCOS, fintech lenders (Tala, Branch, Zenka), insurance companies, payment aggregators (PesaLink, eCitizen), and government revenue authorities (KRA).

Non-finance senders include: marketing/promotional numbers, social media, utilities (unless payment confirmations), ride-hailing, e-commerce order confirmations, and general service notifications that do not involve money.

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

DEFAULT_EXTRACT_BATCH = """You are a financial data extractor. Parse each of the following SMS messages and extract structured financial information.

For each message:
- is_transactional: true if this SMS describes a financial transaction (money movement, balance change, payment, deposit). false if it is a notification (OTP, promo, maintenance alert, general info).
- amount_before: balance before the transaction, if explicitly stated. null otherwise.
- amount_after: balance after the transaction, if explicitly stated. null otherwise.
- amount_changed: the transaction amount. null if not found or not transactional.
- direction: "sent" if money left the account, "received" if money came in, "none" if not applicable.
- transaction_time: any date/time mentioned. null if not present.
- counterparty: the other party. null if not present.
- transaction_reference: any reference code. null if not present.
- transaction_type: "transfer", "payment", "deposit", "withdrawal", "loan", "repayment", "salary", "fee", "interest", "refund", "other", "unknown".

Messages (index | body):
{messages_list}

Respond with a valid JSON array only. One object per message, in the same order:
[
  {
    "body": "original SMS text (truncated to 120 chars)",
    "is_transactional": true/false,
    "amount_before": null or number,
    "amount_after": null or number,
    "amount_changed": null or number,
    "direction": "sent" | "received" | "none",
    "transaction_time": null or string,
    "counterparty": null or string,
    "transaction_reference": null or string,
    "transaction_type": "transfer" | "payment" | "deposit" | "withdrawal" | "loan" | "repayment" | "salary" | "fee" | "interest" | "refund" | "other" | "unknown"
  }
]
"""

# Map of prompt_key -> hardcoded default template. These are the canonical
# defaults and are used whenever no active DB prompt exists for a key.
DEFAULT_PROMPTS = {
    "classify_sender": DEFAULT_CLASSIFY_SENDER,
    "extract_batch": DEFAULT_EXTRACT_BATCH,
}


FINANCE_CATEGORIES = {
    "Mobile Money": {"MPESA", "AIRTELMONEY", "AIRTEL MONEY", "T-KASH", "TELKOM"},
    "Bank": {
        "KCB", "EQUITY", "NCBA", "LOOP", "ABSA", "COOP", "DTB",
        "FAMILY BANK", "I&M", "STANBIC", "STANCHART", "SIDIAN",
        "GULF AFRICAN", "NATIONAL BANK", "NBK", "HFC",
        "PRIME BANK", "CREDIT BANK", "CONSOLIDATED BANK",
        "BANK OF AFRICA", "BOA", "ECOBANK", "UBA", "GTBANK",
        "VICTORIA BANK", "PARAMOUNT BANK", "HOUSING FINANCE",
    },
    "Fintech": {
        "MSHWARI", "M-SHWARI", "TALA", "BRANCH", "ZENKA",
        "TIMIZA", "HUSTLER FUND", "HUSTLERFUND", "STAWI",
        "OKASH", "CREDITBEE", "PESAPAL", "JENGA",
        "KCB M-PESA",
    },
    "SACCO": {
        "STIMA SACCO", "MWALIMU SACCO", "UNAITAS",
        "HARAMBEE SACCO", "KENYA POLICE SACCO",
        "AFYA SACCO", "SAFARICOM SACCO",
    },
    "Insurance": {
        "BRITAM", "JUBILEE INSURANCE", "CIC INSURANCE",
        "APA INSURANCE", "UAP OLD MUTUAL", "MADISON",
    },
    "Payments/Govt": {
        "PESALINK", "PESAFLOW", "KRA", "ECITIZEN",
    },
}
