"""Central configuration. All secrets come from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # Database
    database_url: str = os.getenv("KULISA_DATABASE_URL", "")

    # Listmonk API
    listmonk_url: str = os.getenv("LISTMONK_URL", "http://127.0.0.1:9000")
    listmonk_user: str = os.getenv("LISTMONK_API_USERNAME", "")
    listmonk_token: str = os.getenv("LISTMONK_API_TOKEN", "")

    # Mistral
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

    # Sender identity
    sender_name: str = os.getenv("KULISA_SENDER_NAME", "KULISA Talent Network")
    sender_email: str = os.getenv("KULISA_SENDER_EMAIL", "campaigns@kulisa.example")
    reply_to: str = os.getenv("KULISA_REPLY_TO", "")

    # Safety switches
    sending_enabled: bool = _bool("KULISA_SENDING_ENABLED", "false")
    test_mode: bool = _bool("KULISA_TEST_MODE", "true")

    # Optional reply mailbox (IMAP)
    imap_host: str = os.getenv("KULISA_IMAP_HOST", "")
    imap_user: str = os.getenv("KULISA_IMAP_USER", "")
    imap_password: str = os.getenv("KULISA_IMAP_PASSWORD", "")

    def require(self, *fields: str) -> "Settings":
        missing = [f for f in fields if not getattr(self, f)]
        if missing:
            raise RuntimeError(f"Missing required settings: {', '.join(missing)} (set them in .env)")
        return self


def load_settings() -> Settings:
    return Settings()
