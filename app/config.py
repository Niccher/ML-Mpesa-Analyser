import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class Settings:
    # ── Database details (must be loaded from env/defaults first for DB connection) ──
    db_host: str = os.getenv("DB_HOST", "host.docker.internal")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_name: str = os.getenv("DB_NAME", "mpesa_analyzer")

    def __init__(self):
        self._db_controls: dict[str, str] = {}
        # Core settings holding local engine configurations
        self.llm_engine = "local"
        self.llm_provider = "openai-compatible"
        self.llm_api_key = "not-needed"
        self.llm_base_url = "http://localhost:8080/v1"
        self.llm_model = "qwen2.5-1.5b-instruct"
        self.llm_max_tokens = 2048
        self.llm_temperature = 0.2

        # External cloud LLM configurations
        self.llm_external_provider = "openai-compatible"
        self.llm_external_api_key = ""
        self.llm_external_base_url = ""
        self.llm_external_model = ""
        self.llm_external_max_tokens = 4096
        self.llm_external_temperature = 0.1
        self.external_batch_size = 100
        self.external_max_retries = 3
        self.external_poll_interval = 15

        # Provider specific API keys
        self.llm_gemini_api_key = ""
        self.llm_deepseek_api_key = ""
        self.llm_openai_api_key = ""
        self.llm_groq_api_key = ""
        self.llm_mistral_api_key = ""
        self.llm_openrouter_api_key = ""
        self.llm_cohere_api_key = ""
        self.llm_kimi_api_key = ""
        self.llm_nemotron_api_key = ""
        self.llm_xai_api_key = ""

        # Fallback configurations
        self.llm_fallback_provider = "openai-compatible"
        self.llm_fallback_api_key = ""
        self.llm_fallback_base_url = "https://api.groq.com/openai/v1"
        self.llm_fallback_model = "llama-3.1-8b-instant"
        self.llm_fallback_enabled = False

        # Tuning & Processing configs
        self.llm_ctx_size = 16384
        self.llm_batch_size = 512
        self.n_gpu_layers = 0
        self.batch_size = 5
        self.max_retries = 3
        self.poll_interval = 30

        # Load initial values from environment
        self._load_from_env()

    def _load_from_env(self):
        """Initialise values from environment variables."""
        self.llm_engine = os.getenv("LLM_ENGINE", self.llm_engine)
        self.llm_provider = os.getenv("LLM_PROVIDER", self.llm_provider)
        self.llm_api_key = os.getenv("LLM_API_KEY", self.llm_api_key)
        self.llm_base_url = os.getenv("LLM_BASE_URL", self.llm_base_url)
        self.llm_model = os.getenv("LLM_MODEL", self.llm_model)
        self.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", str(self.llm_max_tokens)))
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", str(self.llm_temperature)))

        self.llm_external_provider = os.getenv("LLM_EXTERNAL_PROVIDER", self.llm_external_provider)
        self.llm_external_api_key = os.getenv("LLM_EXTERNAL_API_KEY", self.llm_external_api_key)
        self.llm_external_base_url = os.getenv("LLM_EXTERNAL_BASE_URL", self.llm_external_base_url)
        self.llm_external_model = os.getenv("LLM_EXTERNAL_MODEL", self.llm_external_model)
        self.llm_external_max_tokens = int(os.getenv("LLM_EXTERNAL_MAX_TOKENS", str(self.llm_external_max_tokens)))
        self.llm_external_temperature = float(os.getenv("LLM_EXTERNAL_TEMPERATURE", str(self.llm_external_temperature)))
        self.external_batch_size = int(os.getenv("EXTERNAL_BATCH_SIZE", str(self.external_batch_size)))
        self.external_max_retries = int(os.getenv("EXTERNAL_MAX_RETRIES", str(self.external_max_retries)))
        self.external_poll_interval = int(os.getenv("EXTERNAL_POLL_INTERVAL", str(self.external_poll_interval)))

        # Provider Keys
        self.llm_gemini_api_key = os.getenv("LLM_GEMINI_API_KEY", self.llm_gemini_api_key)
        self.llm_deepseek_api_key = os.getenv("LLM_DEEPSEEK_API_KEY", self.llm_deepseek_api_key)
        self.llm_openai_api_key = os.getenv("LLM_OPENAI_API_KEY", self.llm_openai_api_key)
        self.llm_groq_api_key = os.getenv("LLM_GROQ_API_KEY", self.llm_groq_api_key)
        self.llm_mistral_api_key = os.getenv("LLM_MISTRAL_API_KEY", self.llm_mistral_api_key)
        self.llm_openrouter_api_key = os.getenv("LLM_OPENROUTER_API_KEY", self.llm_openrouter_api_key)
        self.llm_cohere_api_key = os.getenv("LLM_COHERE_API_KEY", self.llm_cohere_api_key)
        self.llm_kimi_api_key = os.getenv("LLM_KIMI_API_KEY", self.llm_kimi_api_key)
        self.llm_nemotron_api_key = os.getenv("LLM_NEMOTRON_API_KEY", self.llm_nemotron_api_key)
        self.llm_xai_api_key = os.getenv("LLM_XAI_API_KEY", self.llm_xai_api_key)

        # Fallback
        self.llm_fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", self.llm_fallback_provider)
        self.llm_fallback_api_key = os.getenv("LLM_FALLBACK_API_KEY", self.llm_fallback_api_key)
        self.llm_fallback_base_url = os.getenv("LLM_FALLBACK_BASE_URL", self.llm_fallback_base_url)
        self.llm_fallback_model = os.getenv("LLM_FALLBACK_MODEL", self.llm_fallback_model)
        self.llm_fallback_enabled = os.getenv("LLM_FALLBACK_ENABLED", "false").lower() == "true"

        # Tuning
        self.llm_ctx_size = int(os.getenv("LLM_CTX_SIZE", str(self.llm_ctx_size)))
        self.llm_batch_size = int(os.getenv("LLM_BATCH_SIZE", str(self.llm_batch_size)))
        self.n_gpu_layers = int(os.getenv("N_GPU_LAYERS", str(self.n_gpu_layers)))
        self.batch_size = int(os.getenv("BATCH_SIZE", str(self.batch_size)))
        self.max_retries = int(os.getenv("MAX_RETRIES", str(self.max_retries)))
        self.poll_interval = int(os.getenv("POLL_INTERVAL", str(self.poll_interval)))

    async def reload_from_db(self):
        """Fetch all control key-values from tbl_ML_Controls and update settings.

        DB configuration values override environment variables.
        """
        try:
            from app.db.connection import get_engine
            from sqlalchemy import text
            engine = get_engine()
            async with engine.connect() as conn:
                # Check if controls table exists before querying
                table_check = await conn.execute(text("SHOW TABLES LIKE 'tbl_ML_Controls'"))
                if not table_check.fetchone():
                    return

                res = await conn.execute(text("SELECT control_key, control_value FROM tbl_ML_Controls"))
                rows = res.fetchall()
                if not rows:
                    return

                controls = {row[0]: row[1] for row in rows}
                self._db_controls = controls

                # Map database control values onto setting properties (handling type conversion)
                self._apply_db_val("llm_engine", str)
                self._apply_db_val("llm_provider", str)
                self._apply_db_val("llm_api_key", str)
                self._apply_db_val("llm_base_url", str)
                self._apply_db_val("llm_model", str)
                self._apply_db_val("llm_max_tokens", int)
                self._apply_db_val("llm_temperature", float)

                self._apply_db_val("llm_external_provider", str)
                self._apply_db_val("llm_external_api_key", str)
                self._apply_db_val("llm_external_base_url", str)
                self._apply_db_val("llm_external_model", str)
                self._apply_db_val("llm_external_max_tokens", int)
                self._apply_db_val("llm_external_temperature", float)
                self._apply_db_val("external_batch_size", int)
                self._apply_db_val("external_max_retries", int)
                self._apply_db_val("external_poll_interval", int)

                # Provider Keys
                self._apply_db_val("llm_gemini_api_key", str)
                self._apply_db_val("llm_deepseek_api_key", str)
                self._apply_db_val("llm_openai_api_key", str)
                self._apply_db_val("llm_groq_api_key", str)
                self._apply_db_val("llm_mistral_api_key", str)
                self._apply_db_val("llm_openrouter_api_key", str)
                self._apply_db_val("llm_cohere_api_key", str)
                self._apply_db_val("llm_kimi_api_key", str)
                self._apply_db_val("llm_nemotron_api_key", str)
                self._apply_db_val("llm_xai_api_key", str)

                # Fallback
                self._apply_db_val("llm_fallback_provider", str)
                self._apply_db_val("llm_fallback_api_key", str)
                self._apply_db_val("llm_fallback_base_url", str)
                self._apply_db_val("llm_fallback_model", str)
                self._apply_db_val("llm_fallback_enabled", lambda v: v.lower() in ("1", "true", "yes", "on"))

                # Tuning
                self._apply_db_val("llm_ctx_size", int)
                self._apply_db_val("llm_batch_size", int)
                self._apply_db_val("n_gpu_layers", int)
                self._apply_db_val("batch_size", int)
                self._apply_db_val("max_retries", int)
                self._apply_db_val("poll_interval", int)

                logger.info(f"Loaded {len(controls)} configurations from tbl_ML_Controls. Current Engine: {self.llm_engine}")
        except Exception as e:
            logger.warning(f"Failed to load configurations from database: {e}")

    def _apply_db_val(self, key: str, type_converter):
        if key in self._db_controls:
            val = self._db_controls[key]
            if val is not None and val != "":
                try:
                    setattr(self, key, type_converter(val))
                except Exception as e:
                    logger.warning(f"Failed to convert control value '{val}' for key '{key}': {e}")

    @property
    def db_url(self) -> str:
        return (
            f"mysql+asyncmy://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


settings = Settings()

