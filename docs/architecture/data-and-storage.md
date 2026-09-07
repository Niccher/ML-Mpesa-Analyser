# Data Architecture & Storage Design

The system relies on a single shared MySQL 8.4 database (`db_mpesa_analyzer`). This document describes the database design principles, canonical record structure, relational entity mappings, and analytical views.

---

## 1. Entity-Relationship Diagram (ERD)

The diagram below illustrates relationships between device registration, uploaded payload batches, canonical SMS storage, and background ML processing jobs:

```mermaid
erDiagram
    users ||--o{ tbl_User_Devices : "owns"
    tbl_Devices ||--o{ tbl_User_Devices : "bound to"
    users ||--o{ tbl_Loot : "uploads"
    tbl_Loot ||--|{ tbl_Sms : "contains"
    tbl_Sms ||--o| tbl_Sms_Processing : "tracked by"
    users ||--o{ tbl_Processing_Jobs : "triggers"
    tbl_Sms ||--o| tbl_Sender_Profiles : "matched to"

    users {
        int id PK
        string username
        string email
    }

    tbl_Devices {
        int device_id PK
        string device_print
        string model
        string brand
    }

    tbl_User_Devices {
        int id PK
        int user_id FK
        int device_id FK
    }

    tbl_Loot {
        int loot_id PK
        string loot_uuid
        int user_id FK
        datetime created_at
    }

    tbl_Sms {
        int sms_id PK
        int loot_id FK
        int user_id FK
        string sms_sender
        text sms_body
        string sms_category
        boolean sms_is_finance
        float sms_confidence
        string sms_direction
        decimal sms_amount
        decimal sms_balance
        string sms_counterparty
        string sms_transaction_type
        boolean sms_is_transactional
        string sms_trans_id
        datetime sms_trans_date
    }

    tbl_Sms_Processing {
        int sms_id PK,FK
        string status
        int attempt_count
        text error_message
    }

    tbl_Processing_Jobs {
        int job_id PK
        int user_id FK
        string status
        json metadata
        datetime created_at
    }

    tbl_Sender_Profiles {
        int sp_id PK
        string sp_number
        string sp_name
        string sp_category
        boolean sp_is_finance
        float sp_confidence
    }

    tbl_Allowed_Senders {
        int id PK
        string sender
        string category
    }
```

---

## 2. Single Canonical Record (`tbl_Sms`)

To avoid duplicate writes and synchronization drift between classification and extraction, all attributes for an individual SMS message live on a **single canonical row** in `tbl_Sms`.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        tbl_Sms (Canonical Record)                       │
├────────────────────────────────────────────────────────────────────────┤
│ • Ingestion Metadata:   sms_id, user_id, loot_id, sender, raw_body     │
│ • Classification:       sms_category, sms_is_finance, sms_confidence   │
│ • Extraction Fields:    sms_direction, sms_amount, sms_balance,        │
│                         sms_counterparty, sms_transaction_type,        │
│                         sms_is_transactional, sms_trans_id,            │
│                         sms_trans_date                                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│  VIEW tbl_Sms_Classification  │               │ VIEW tbl_Analyzed_Transactions│
│  (Derived classification map) │               │ (Derived transactional subset)│
└───────────────────────────────┘               └───────────────────────────────┘
```

The database views `tbl_Sms_Classification` and `tbl_Analyzed_Transactions` are **read-only projections** over `tbl_Sms`. The ML service writes once to `tbl_Sms`, and the web application queries the views for reporting. For architectural rationale, see [ADR 0001: Single Canonical SMS Record](../adr/0001-single-canonical-sms-record.md).

---

## 3. Sender Profile & Allowlist Strategy

1. **`tbl_Allowed_Senders`**: Global database allowlist populated with verified Kenyan financial senders. Entries here bypass LLM classification entirely and receive immediate `0.95` confidence.
2. **`tbl_Sender_Profiles`**: Cached sender catalog generated dynamically by the classifier. Once an unknown sender is evaluated by the LLM, the result is saved here to prevent subsequent LLM calls.
3. **`tbl_Blocked_Senders`**: Per-user exclusions for marketing or non-relevant sender numbers.

---

## 4. Job Execution & Audit Tracking

- **`tbl_Processing_Jobs`**: Every batch run or user-triggered rescan inserts a job row. The `metadata` column stores a detailed JSON document detailing:
  - Total SMS processed, financial count, skipped count
  - Category and direction distribution
  - Model path, LLM context size, temperature, and batch configuration
  - Execution duration in seconds and error logs
- **`tbl_ML_Controls`**: Contains persistent system toggles, notably `auto_jobs_enabled`, which allows operators to pause background processing.
- **`tbl_LLM_Prompts`**: Stores versioned prompt templates. Edits made in the admin UI create new versions rather than overwriting historical prompts.
