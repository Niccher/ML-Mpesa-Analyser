# ML Mpesa Analyzer — Engineering Documentation

Welcome to the engineering documentation for **ML Mpesa Analyzer**, the autonomous LLM inference and financial intelligence microservice for the M-Pesa Analyzer ecosystem.

This repository serves as the central **System Architecture Anchor** for the three-repo polyrepo.

---

## Documentation Index

| I want to… | Go here |
|------------|---------|
| **Run the service as an operator** | [../README.md](../README.md) |
| **Understand system architecture & C4 containers** | [architecture/overview.md](architecture/overview.md) |
| **Trace end-to-end communication & sequences** | [architecture/communication.md](architecture/communication.md) |
| **Inspect database schemas, ERD & canonical records** | [architecture/data-and-storage.md](architecture/data-and-storage.md) |
| **Understand container & process lifecycle** | [architecture/deployment.md](architecture/deployment.md) |
| **Review FastAPI REST & Admin API contracts** | [api/contract.md](api/contract.md) |
| **Work on the FastAPI backend & routers** | [services/fastapi.md](services/fastapi.md) |
| **Work on LLM models, prompts, & inference** | [services/ml.md](services/ml.md) |
| **Set up a native Python development environment** | [engineering/local-development.md](engineering/local-development.md) |
| **Add new endpoints or change classification rules** | [engineering/making-changes.md](engineering/making-changes.md) |
| **Query patterns and database connection handling** | [engineering/database.md](engineering/database.md) |
| **Run automated unit & schema test suites** | [engineering/testing.md](engineering/testing.md) |
| **Solve engineering & runtime issues** | [engineering/troubleshooting.md](engineering/troubleshooting.md) |
| **Follow contribution & definition-of-done guidelines** | [engineering/contributing.md](engineering/contributing.md) |
| **Operational Runbook: Upgrading GGUF models** | [runbooks/model-upgrade.md](runbooks/model-upgrade.md) |
| **ADR 0001: Single canonical SMS record design** | [adr/0001-single-canonical-sms-record.md](adr/0001-single-canonical-sms-record.md) |
| **ADR 0002: Local CPU inference vs cloud APIs** | [adr/0002-local-cpu-llm-vs-hosted-apis.md](adr/0002-local-cpu-llm-vs-hosted-apis.md) |

---

## Ecosystem Sibling Repositories

- **Web Dashboard & Gateway**: [Niccher/MPesa-Analyzer-WebApp](https://github.com/Niccher/MPesa-Analyzer-WebApp) (CodeIgniter 4, MySQL 8.4, Shield)
- **Android Mobile Client**: [Niccher/MPesa-Analyzer-App](https://github.com/Niccher/MPesa-Analyzer-App) (Kotlin, Retrofit, Jetpack Compose)
