import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

POSTGRES_DB = os.getenv("POSTGRES_DB", "campus_security")
POSTGRES_USER = os.getenv("POSTGRES_USER", "campus_admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "campus_dev_pass")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "frigate")

FRIGATE_HOST = os.getenv("FRIGATE_HOST", "localhost")
FRIGATE_PORT = int(os.getenv("FRIGATE_PORT", "5000"))

N8N_PORT = int(os.getenv("N8N_PORT", "5678"))
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/test-invoice")

WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "mock")

# Authentication (Phase 5C). Set AUTH_SECRET_KEY in .env; without it a random
# per-process key is used and every issued token becomes invalid on restart.
# A guessable key lets anyone sign an ADMIN token (user ids are visible to staff), so refuse one.
_configured_secret = os.getenv("AUTH_SECRET_KEY")
if _configured_secret and (_configured_secret == "change-me" or len(_configured_secret) < 32):
    raise RuntimeError(
        "AUTH_SECRET_KEY is the .env.example placeholder or shorter than 32 characters. Generate one with: "
        "python -c \"import secrets;print(secrets.token_urlsafe(48))\""
    )
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY") or secrets.token_urlsafe(48)
AUTH_SECRET_KEY_IS_EPHEMERAL = not os.getenv("AUTH_SECRET_KEY")
AUTH_TOKEN_TTL_MINUTES = int(os.getenv("AUTH_TOKEN_TTL_MINUTES", "720"))

# Registry linkage of observations (Phase 5C)
# Plate reads below this confidence are LOW_CONFIDENCE and get fuzzy suggestions.
RESOLUTION_CONFIDENCE_THRESHOLD = float(os.getenv("RESOLUTION_CONFIDENCE_THRESHOLD", "0.80"))
RESOLUTION_SUGGESTION_MIN_SIMILARITY = float(os.getenv("RESOLUTION_SUGGESTION_MIN_SIMILARITY", "0.70"))
RESOLUTION_SUGGESTION_LIMIT = int(os.getenv("RESOLUTION_SUGGESTION_LIMIT", "5"))

# Live feed (Phase 5C)
FEED_STREAM_POLL_SECONDS = float(os.getenv("FEED_STREAM_POLL_SECONDS", "1.0"))
FEED_REGISTRY_LOOKBACK_HOURS = int(os.getenv("FEED_REGISTRY_LOOKBACK_HOURS", "24"))

# Longest validity window a GUARD/SUPERVISOR may give a VISITOR/DELIVERY registration
GUARD_REGISTRATION_MAX_VALIDITY_HOURS = int(os.getenv("GUARD_REGISTRATION_MAX_VALIDITY_HOURS", "168"))

# Movement logging & presence (Phase 6). Unverified starting values; recalibrate on PEC footage.
MOVEMENT_DEBOUNCE_SECONDS = int(os.getenv("MOVEMENT_DEBOUNCE_SECONDS", "60"))
PRESENCE_LONG_STAY_HOURS = float(os.getenv("PRESENCE_LONG_STAY_HOURS", "24"))
PRESENCE_UNATTRIBUTED_LOOKBACK_HOURS = int(os.getenv("PRESENCE_UNATTRIBUTED_LOOKBACK_HOURS", "24"))
