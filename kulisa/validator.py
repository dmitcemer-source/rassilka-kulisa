"""Email validation and normalization.

Offline checks: syntax, normalization, disposable domains, role-based flags.
MX lookups are optional (enable via KULISA_CHECK_MX=1 with dnspython installed).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "trashmail.com", "yopmail.com", "getnada.com", "dispostable.com",
    "sharklasers.com", "throwawaymail.com",
}

ROLE_PREFIXES = {
    "info", "office", "contact", "admin", "webmaster", "postmaster",
    "noreply", "no-reply", "support", "help", "sales", "marketing",
}


@dataclass
class ValidationResult:
    email: str
    status: str          # valid | invalid | risky
    reason: str = ""


def normalize(email: str) -> str:
    return email.strip().strip("<>").lower()


def validate(raw_email: str) -> ValidationResult:
    email = normalize(raw_email or "")
    if not email:
        return ValidationResult("", "invalid", "empty address")
    if " " in email or not EMAIL_RE.match(email):
        return ValidationResult(email, "invalid", "syntax")
    domain = email.split("@", 1)[1]
    if domain in DISPOSABLE_DOMAINS:
        return ValidationResult(email, "invalid", "disposable domain")
    local = email.split("@", 1)[0]
    if local.split("+", 1)[0] in ROLE_PREFIXES:
        return ValidationResult(email, "risky", "role-based address")
    if os.getenv("KULISA_CHECK_MX", "0") == "1":
        try:
            import dns.resolver  # type: ignore

            answers = dns.resolver.resolve(domain, "MX", raise_on_no_answer=False)
            if not answers:
                return ValidationResult(email, "invalid", "no MX record")
        except Exception as exc:  # noqa: BLE001 - offline environments
            return ValidationResult(email, "risky", f"mx check unavailable: {exc}")
    return ValidationResult(email, "valid")


COUNTRY_LANGUAGE = {
    "germany": "de", "austria": "de", "switzerland": "de",
    "france": "fr", "belgium": "fr", "spain": "es", "italy": "it",
    "netherlands": "nl", "poland": "pl", "portugal": "pt",
    "sweden": "sv", "norway": "no", "denmark": "da", "finland": "fi",
    "czech republic": "cs", "czechia": "cs", "hungary": "hu", "romania": "ro",
    "united kingdom": "en", "ireland": "en", "united states": "en",
    "canada": "en", "australia": "en", "new zealand": "en",
}

ORG_TYPES = {
    "theatre", "theater", "theatre company", "theater company", "producer",
    "production company", "festival", "performing arts", "agency", "opera",
    "dance", "venue", "other",
}


def infer_language(country: str | None) -> str:
    if not country:
        return "en"
    return COUNTRY_LANGUAGE.get(country.strip().lower(), "en")


def infer_org_type(raw: str | None) -> str:
    if not raw:
        return "other"
    value = raw.strip().lower()
    for candidate in ORG_TYPES:
        if candidate in value:
            return candidate
    return "other"
