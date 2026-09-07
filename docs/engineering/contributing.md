# Contributing Guidelines — ML Mpesa Analyzer

Guidelines for submitting bug fixes and feature enhancements.

---

## 1. Branching Strategy

- **`main`**: Production-ready branch.
- **Feature Branches**: Create descriptive branches formatted as `feature/your-feature-name` or `fix/issue-description`.

---

## 2. Pull Request Workflow

1. Fork or branch from `main`.
2. Make code edits and add accompanying test cases in `tests/`.
3. Run test suite:
   ```bash
   python3 -m pytest tests/
   ```
4. Verify documentation is updated across `docs/` and run the documentation linter:
   ```bash
   python3 /home/niccher/Downloads/readme-docs-skill/readme-docs-skill/scripts/lint-docs.py .
   ```
5. Submit PR with clear summary of behavioral and schema impacts.
