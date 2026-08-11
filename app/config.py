import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # LLM (local llama.cpp by default)
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai-compatible")
    llm_api_key: str = os.getenv("LLM_API_KEY", "not-needed")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:8080/v1")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5-1.5b-instruct")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))

    # llama.cpp server tuning (applied on restart via entrypoint)
    llm_ctx_size: int = int(os.getenv("LLM_CTX_SIZE", "16384"))
    llm_batch_size: int = int(os.getenv("LLM_BATCH_SIZE", "512"))
    n_gpu_layers: int = int(os.getenv("N_GPU_LAYERS", "0"))

    # DB
    db_host: str = os.getenv("DB_HOST", "host.docker.internal")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_name: str = os.getenv("DB_NAME", "mpesa_analyzer")

    # Processing
    batch_size: int = int(os.getenv("BATCH_SIZE", "5"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "30"))

    @property
    def db_url(self) -> str:
        return (
            f"mysql+asyncmy://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


settings = Settings()
