# Troubleshooting Guide (Operator) — ML Mpesa Analyzer

Common symptoms and resolutions when running the ML container.

---

## 1. Container Exits Immediately or Fails Healthcheck

**Symptom**: `curl http://localhost:9050/health` returns `Connection refused` or `502`.

**Cause**: The GGUF model file is missing from `models/` or corrupted during download.

**Remedy**:
1. Check container logs:
   ```bash
   docker compose logs ml-mpesa-analyzer
   ```
2. Verify the model file exists and is larger than 1 GB:
   ```bash
   ls -lh models/
   ```
3. Re-download if empty or incomplete:
   ```bash
   wget -P models/ https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
   ```

---

## 2. Port Conflicts on 9050 or 8080

**Symptom**: `bind: address already in use` error when running `docker compose up`.

**Remedy**:
Adjust host mapped ports in your `.env` or `docker-compose.yml`:
- Set `ML_MPESA_ANALYZER_API_PORT=9051`
- Set `ML_MPESA_ANALYZER_LLAMA_PORT=8081`

---

## 3. Database Connection Failure

**Symptom**: Logs display `Can't connect to MySQL server on 'mysql'`.

**Remedy**:
1. Confirm that the web backend / shared MySQL container is running on the network:
   ```bash
   docker network ls | grep hosts-shared-network
   ```
2. Test MySQL reachability from inside the network:
   ```bash
   docker compose run --rm ml-mpesa-analyzer curl -v telnet://mysql:3306
   ```
3. Verify credentials in `.env` match `Mpesa Analyzer WebApp` credentials.

---

## 4. Background Poller Appears Idle

**Symptom**: New SMS records exist in `tbl_Sms`, but extraction does not occur.

**Remedy**:
1. Check whether the admin auto-jobs toggle is disabled:
   ```bash
   curl http://localhost:9050/admin/jobs/status
   ```
2. Re-enable the poller:
   ```bash
   curl -X POST http://localhost:9050/admin/jobs/auto -H "Content-Type: application/json" -d '{"enabled": true}'
   ```
