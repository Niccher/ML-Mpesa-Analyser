# Inter-Service Communication & Protocols

This document details transport protocols, sequences, and security contracts between the Android application, CodeIgniter 4 WebApp, and the FastAPI ML service.

---

## 1. Service Communication Matrix

| Source | Destination | Transport | Auth Mechanism | Dev URL | Purpose |
|--------|-------------|-----------|----------------|---------|---------|
| **Android App** | WebApp API | HTTP POST | Bearer SHA-256 Token | `http://10.0.2.2:9002/api/v1/` | Payload upload, stats fetch, auth |
| **WebApp** | ML Service | HTTP POST | Internal network | `http://ml-mpesa-analyzer:9050/` | Trigger user job, rescan, health |
| **WebApp** | MySQL | TCP (3306) | User/Password | `mysql:3306` | Web queries, Shield auth, inserts |
| **ML Service** | MySQL | TCP (3306) | User/Password | `mysql:3306` | Polling, canonical SMS updates |
| **FastAPI** | llama-server | HTTP POST | Localhost loopback | `http://localhost:8080/v1` | OpenAI-compatible completions |

---

## 2. End-to-End Ingestion & Processing Flow

```mermaid
sequenceDiagram
  autonumber
  participant App as Android Client
  participant Web as CI4 WebApp
  participant DB as MySQL 8.4
  participant ML as FastAPI Service
  participant LLM as llama-server

  App->>App: Read SMS & AES-128 Encrypt (dynamic IV)
  App->>Web: POST /api/v1/upload (loot stream)
  Web->>Web: Decrypt stream & parse JSON
  Web->>DB: INSERT into tbl_Sms & tbl_Loot
  Web->>ML: POST /process/for-user/{id} (or poller picks up)
  ML->>DB: SELECT unprocessed from tbl_Sms
  ML->>ML: Match sender in tbl_Allowed_Senders / known dict
  alt Unknown Sender
    ML->>LLM: POST /v1/chat/completions (classify sender)
    LLM-->>ML: Return {is_finance, category, confidence}
    ML->>DB: UPSERT tbl_Sender_Profiles
  end
  alt Finance Sender
    ML->>LLM: POST /v1/chat/completions (extract transactions)
    LLM-->>ML: Structured JSON (amount, direction, balance)
  end
  ML->>DB: UPDATE tbl_Sms (single canonical record)
  ML->>DB: INSERT tbl_Processing_Jobs (audit & metrics)
  App->>Web: POST /api/v1/financial/overview
  Web-->>App: Return classified financial summaries
```

---

## 3. Security & Payload Protocol

### Dynamic IV AES-128-CBC
1. **Client Streaming**: The Android app generates a 16-byte cryptographically secure random IV (`SecureRandom`).
2. **IV Prefixing**: The IV is written as the first 16 bytes of the binary payload stream.
3. **Payload**: The remainder of the stream contains the AES-128-CBC encrypted JSON body.
4. **Server Decryption**: The CI4 WebApp reads the initial 16 bytes, sets it as the IV, and executes `openssl_decrypt()`.

---

## 4. API Error Body Convention

All JSON API endpoints conform to a standardized error envelope:

```json
{
  "status": "error",
  "message": "Human-readable description of error",
  "code": 400,
  "errors": {
    "field_name": ["Specific validation error"]
  }
}
```
