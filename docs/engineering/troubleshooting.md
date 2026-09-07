# Developer Troubleshooting — ML Mpesa Analyzer

Technical debugging for software engineers working on the Python codebase.

---

## 1. Pydantic ValidationError on Extraction

**Symptom**: `ValidationError: 1 validation error for TransactionExtraction` in logs.

**Cause**: The LLM returned non-compliant JSON or omitted a required field.

**Remedy**:
1. Check `tests/test_schemas.py` to confirm the expected field structure.
2. Inspect the raw LLM response in `app/services/extractor.py`.
3. Increase prompt constraints or few-shot examples in `app/utils/prompt_templates.py`.

---

## 2. llama-server `shared library missing: libgomp.so.1`

**Symptom**: llama-server fails to start natively on Linux with missing shared library.

**Remedy**:
Install OpenMP support package:
```bash
sudo apt-get update && sudo apt-get install -y libgomp1
```

---

## 3. Asynchronous MySQL Connection Timeout

**Symptom**: `OperationalError: (2006, 'MySQL server has gone away')`.

**Remedy**:
Verify `pool_recycle=3600` is active in `app/db/connection.py`. Ensure MySQL container is running on the expected port.
