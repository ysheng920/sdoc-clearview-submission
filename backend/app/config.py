import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local .env if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

DATA_DIR = Path(os.environ.get("SDOC_DATA_DIR", BASE_DIR / "data"))
INBOX_DIR = DATA_DIR / "inbox"
DB_PATH = Path(os.environ.get("SDOC_DB", BASE_DIR / "clearview.db"))

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
# OpenRouter namespaces the same model; Google's own endpoint does not. This
# deployment has no Google key, so the namespaced slug is the one actually used.
GEMINI_MODEL_OPENROUTER = os.environ.get(
    "GEMINI_MODEL_OPENROUTER",
    GEMINI_MODEL if "/" in GEMINI_MODEL else f"google/{GEMINI_MODEL}")
CLASSIFICATION_FALLBACK_THRESHOLD = float(
    os.environ.get("CLASSIFICATION_FALLBACK_THRESHOLD", "0.80")
)

if os.environ.get("LLM_BACKEND"):
    LLM_BACKEND = os.environ.get("LLM_BACKEND").lower()
elif os.environ.get("GEMINI_API_KEY"):
    LLM_BACKEND = "gemini"
elif os.environ.get("OPENROUTER_API_KEY"):
    LLM_BACKEND = "openrouter"
else:
    # No provider key. The deterministic path still parses documents and compares
    # them; it just cannot classify, and says so rather than guessing.
    LLM_BACKEND = "deterministic"

default_model = GEMINI_MODEL
MODEL = os.environ.get("MODEL", os.environ.get("GEMINI_MODEL", default_model))
CLOUD_MODEL = MODEL

# Legacy compatibility flags (direct model execution without two-tier escalation)
ESCALATE_LOGP = 0.0
ESCALATION_ENABLED = False

# A provider call that never returns is the worst kind: the SDK default is
# 600s with two retries, so one stalled socket can hold a worker for half an
# hour while the run reports no progress at all.
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "45"))
REQUEST_RETRIES = int(os.environ.get("REQUEST_RETRIES", "1"))
# How long one email may take before the run stops waiting on it and records it
# as failed. Generous: it only has to catch a genuine stall.
EMAIL_TIMEOUT = float(os.environ.get("EMAIL_TIMEOUT", "180"))

MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1000"))
WORKERS = int(os.environ.get("WORKERS", "10"))

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
FIELDS = [
    "shipper", "consignee", "notify_party", "port_of_loading",
    "port_of_discharge", "container_count", "gross_weight_kg",
]
