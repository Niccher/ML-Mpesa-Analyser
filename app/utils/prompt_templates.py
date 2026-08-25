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

BATCH_EXTRACT_PROMPT = """You are a Senior Financial Analyst and Personal Wealth Advisor. Parse each of the following SMS messages and extract structured financial information, cash flow trends, normality assessment, and financial advisory warnings.

For each message, extract according to these rules:
- is_transactional: true if this SMS describes a financial transaction (money movement, balance change, payment, deposit, etc.). false if it is a notification (OTP, promo, maintenance alert, account opening confirmation, general info).
- amount_before: the account balance before the transaction, if explicitly stated. null otherwise.
- amount_after: the account balance after the transaction, if explicitly stated. null otherwise.
- amount_changed: the monetary amount involved in the transaction. null if not found or not transactional.
- direction: "sent" if money left the account, "received" if money came in, "none" if not applicable.
- fee: the transaction cost, transfer fee, convenience fee, or charge. null if not stated.
- is_reversal: true if this message describes a reversal, cancellation, failed transaction, or refunded transaction. false otherwise.
- is_loan: true if this is a loan disbursement (credit/incoming cash from lending services like KCB M-Pesa, M-Shwari, Fuliza, Tala, Branch). false otherwise.
- transaction_time: any date or time mentioned in the message. return as ISO-like string or the exact text. null if not present.
- counterparty: the other person, business, or institution on the other side of the transaction. null if not present or not transactional.
- transaction_reference: any transaction code, receipt number, or reference ID. null if not present.
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

Respond with a valid JSON array only, one object per message in the same order. Use this exact schema per item:
{{
    "body": "original SMS text (truncated to 120 chars if long)",
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
}}
"""

# Hardcoded default prompts, used when no DB version is active for a key.
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

DEFAULT_EXTRACT_BATCH = """You are a Senior Financial Analyst and Personal Wealth Advisor. Parse each of the following SMS messages and extract structured financial information, cash flow trends, normality assessment, and financial advisory warnings.

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
        "NCBA_BANK", "NCBA_INFO", "IANDMBANK", "KCBINFO", "EQUITY BANK",
    },
    "Fintech": {
        "MSHWARI", "M-SHWARI", "TALA", "BRANCH", "ZENKA",
        "TIMIZA", "HUSTLER FUND", "HUSTLERFUND", "STAWI",
        "OKASH", "CREDITBEE", "PESAPAL", "JENGA",
        "KCB M-PESA", "OKOA", "FULIZA", "GLOBALPAY",
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
