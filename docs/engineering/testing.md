# Testing Guide — ML Mpesa Analyzer

Automated tests are written with `pytest` and reside in `tests/`.

---

## 1. Running Test Suites

From the repository root with virtual environment activated:

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run schema validation tests
python3 -m pytest tests/test_schemas.py -v

# Run sender classifier unit tests
python3 -m pytest tests/test_classifier.py -v
```

---

## 2. Test Coverage Scope

- **`test_schemas.py`**: Verifies Pydantic model serialization, required attributes, confidence range constraints (0.0–1.0), and JSON conversion adherence.
- **`test_classifier.py`**: Verifies dictionary lookup against the 60+ known sender allowlist, category mapping, and confidence score assignments without issuing live network calls to the LLM.
