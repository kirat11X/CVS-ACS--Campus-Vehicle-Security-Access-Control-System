import logging
import os

from backend.app.config import SIMULATION_MODE, WHATSAPP_PROVIDER
from backend.app.whatsapp.base import WhatsAppProvider
from backend.app.whatsapp.mock import MockWhatsAppProvider, mock_whatsapp
from backend.app.whatsapp.local import LocalIntakeProvider, LocalIntakeWhatsAppProvider
from backend.app.whatsapp.meta import MetaCloudWhatsAppProvider, CloudAPIWhatsAppProvider

logger = logging.getLogger("campus_security.whatsapp")

_provider = None

def get_whatsapp_provider() -> WhatsAppProvider:
    """The provider selected by WHATSAPP_PROVIDER and SIMULATION_MODE."""
    global _provider
    if _provider is None:
        # Check simulation mode via environment or config
        sim_env = os.getenv("SIMULATION_MODE", "").strip().lower() in ("true", "1", "yes")
        is_simulation = SIMULATION_MODE or sim_env
        provider_name = os.getenv("WHATSAPP_PROVIDER", WHATSAPP_PROVIDER).strip().lower()

        if is_simulation or provider_name == "mock":
            _provider = mock_whatsapp
        elif provider_name in ("meta", "cloud", "cloudapi"):
            _provider = CloudAPIWhatsAppProvider()
        else:
            if provider_name != "local":
                logger.warning("Unknown WHATSAPP_PROVIDER '%s'; using the local intake provider.", provider_name)
            _provider = LocalIntakeWhatsAppProvider()
    return _provider

__all__ = [
    "WhatsAppProvider",
    "MockWhatsAppProvider",
    "LocalIntakeProvider",
    "LocalIntakeWhatsAppProvider",
    "MetaCloudWhatsAppProvider",
    "CloudAPIWhatsAppProvider",
    "mock_whatsapp",
    "get_whatsapp_provider",
]
