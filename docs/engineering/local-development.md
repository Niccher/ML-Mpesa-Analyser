# Local Development Setup — ML Mpesa Analyzer

For software engineers working on Python code, routers, or schemas without running inside Docker.

---

## 1. Prerequisites

- **Python 3.12+**
- Pre-built **llama-server** binary placed in `llama-bin/` (or running elsewhere)
- Running **MySQL 8.4** instance (can use Docker for MySQL: `docker compose up mysql -d` from the WebApp directory)

---

## 2. Environment Setup

### Step 1: Create and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Configure Local Environment
```bash
cp .env.example .env
```
Edit `.env` to point `DB_HOST=127.0.0.1`, `DB_PORT=9306` (or whichever port host MySQL is exposed on).

### Step 4: Run llama-server
In a separate terminal:
```bash
./llama-bin/llama-server \
    --model models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
    --port 8080 \
    --ctx-size 16384 \
    --mlock
```

### Step 5: Run FastAPI with Live Reload
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 9050
```

FastAPI interactive documentation is available at `http://localhost:9050/docs`.
