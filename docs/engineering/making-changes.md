# Making Changes — Engineering Guide

This guide outlines common development tasks and the Definition of Done for pull requests.

---

## 1. Task Navigator

| If you want to… | Files to modify |
|-----------------|-----------------|
| **Add a new extraction field** (e.g. transaction fees) | 1. Update `app/models/schemas.py`<br/>2. Update `extract_batch` prompt in `app/utils/prompt_templates.py`<br/>3. Update `upsert_sms_analysis` in `app/db/queries.py`<br/>4. Coordinate migration in WebApp (`tbl_Sms`) |
| **Add an admin management endpoint** | 1. Add route handler in `app/routers/admin.py`<br/>2. Define schemas in `app/models/schemas.py`<br/>3. Add queries in `app/db/queries.py` |
| **Add a known financial sender to fallback dictionary** | Edit `FINANCE_CATEGORIES` dictionary in `app/utils/prompt_templates.py` |
| **Adjust background poller interval or batch size** | Update default values in `app/config.py` and document in `docs/user/configuration.md` |
| **Alter LLM prompt structure** | Update prompt functions in `app/utils/prompt_templates.py` or seed via `seed_prompts.py` |

---

## 2. Definition of Done (DoD)

Before merging any change:

- [ ] Code follows PEP 8 conventions and type hints.
- [ ] Schema changes reflected in `app/models/schemas.py`.
- [ ] Automated tests updated and passing via `pytest tests/`.
- [ ] Database schema changes coordinated with WebApp migrations.
- [ ] Documentation updated in `docs/api/contract.md` or `docs/services/ml.md` if contracts changed.
- [ ] No secrets or sensitive configuration committed.
