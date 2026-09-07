# System Architecture Overview

This document defines the C4 Context and Container boundaries for the **M-Pesa Analyzer** three-repository ecosystem.

---

## 1. High-Level Context

The system automates the ingestion, client-side encryption, server-side storage, and local AI enrichment of mobile money SMS notifications from Kenyan financial institutions (M-PESA, banks, SACCOs, fintechs).

```mermaid
flowchart TD
  User((End User))

  subgraph Mobile Device
    App[Android App<br/>Mpesa_Analyzer_App]
  end

  subgraph Server Infrastructure
    WebApp[Web & API Backend<br/>CodeIgniter 4<br/>Port 9002]
    ML[ML Intelligence Service<br/>FastAPI + llama-server<br/>Port 9050 / 8080]
    MySQL[(Shared MySQL 8.4<br/>db_mpesa_analyzer<br/>Port 3306 / 9306)]
  end

  User -->|Reads SMS / Views UI| App
  User -->|Browser Dashboard| WebApp
  App -->|Encrypted Payload HTTP POST| WebApp
  WebApp -->|Store & Fetch SMS| MySQL
  ML -->|Poll & Single Canonical Write| MySQL
  WebApp -->|Trigger Job / Rescan| ML
```

---

## 2. Container Responsibilities & Technologies

| Container / Component | Repository | Runtime | Ownership & Role |
|-----------------------|------------|---------|------------------|
| **Android App** | `Mpesa_Analyzer_App` | Kotlin, Android SDK 35, Jetpack Compose | Captures local SMS, performs regex pre-classification, AES-128-CBC encrypts, and streams uploads to WebApp. |
| **Web & API Backend** | `Mpesa Analyzer WebApp` | PHP 8.3, Apache, CodeIgniter 4, Shield | Decrypts payloads, persists raw SMS in `tbl_Sms`, exposes dashboard UI, manages user accounts and budgets. |
| **ML Intelligence** | `ML Mpesa Analyzer` | Python 3.12, FastAPI, llama-server, Qwen2.5 1.5B | Autonomous background polling, known-sender dictionary lookup, LLM sender classification, and batch transaction extraction. |
| **Database** | Shared Container | MySQL 8.4 (InnoDB) | Central storage for raw SMS, classification profiles, transactions, and audit jobs. |

---

## 3. Trust Boundaries & Authentication

1. **Android Client $\to$ WebApp API**:
   - Authenticated via SHA-256 Access Tokens (`auth_identities` table managed by Shield).
   - Payloads are encrypted client-side using dynamic IV AES-128-CBC; backend decrypts via `openssl_decrypt()`.
2. **Browser $\to$ WebApp Dashboard**:
   - Session-cookie authenticated via CodeIgniter Shield.
   - Global CSRF token verification enabled on all mutating POST requests.
3. **WebApp $\to$ ML Service**:
   - Internal Docker network (`hosts-shared-network`) communication on `http://ml-mpesa-analyzer:9050`.
   - Admin management protected by WebApp session role filtering (`admin` filter).
4. **ML Service $\to$ MySQL**:
   - Direct connection via asynchronous SQLAlchemy engine (`aiomysql`).
   - Gated by admin control flag (`tbl_ML_Controls.auto_jobs_enabled`).
