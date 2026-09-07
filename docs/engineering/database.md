# Database Engineering — ML Mpesa Analyzer

Details of database interaction, query patterns, and connection pooling.

---

## 1. Schema Ownership

The database schema and migrations are **owned by the CodeIgniter 4 WebApp** (`Mpesa Analyzer WebApp/app/Database/Migrations`). The ML service does not execute DDL migrations; it consumes and updates existing tables.

---

## 2. Connection Engine

The database connection is established asynchronously in `app/db/connection.py` using `SQLAlchemy` with the `aiomysql` driver:

```python
# Connection string format
DATABASE_URL = f"mysql+aiomysql://{user}:{password}@{host}:{port}/{name}"
```

- **Connection Pool**: Default pool size of 5 with 10 max overflow connections.
- **Health Verification**: Periodic ping checks ensure stale connections dropped by MySQL wait timeouts are recycled automatically.

---

## 3. Query Modules

All queries reside in `app/db/queries.py`:

- `get_unprocessed_sms(limit)`: Fetches pending rows where `tbl_Sms_Processing.status` is null or `error`.
- `upsert_sms_analysis(...)`: Writes atomic classification and extracted transaction fields to `tbl_Sms`.
- `upsert_sender_profile(...)`: Caches sender categorization in `tbl_Sender_Profiles`.
- `record_processing_job(...)`: Writes job completion telemetry and execution metadata to `tbl_Processing_Jobs`.
