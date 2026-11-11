"""Personalized email generation powered by Mistral.

Falls back to a deterministic template when no MISTRAL_API_KEY is configured
(test mode), so the whole workflow can be demonstrated without live API calls.
"""
from __future__ import annotations

import json

import httpx

from .config import Settings

SYSTEM_PROMPT = """You are the campaign copywriter for KULISA Talent Network, a professional \
talent network serving theatres, theatre companies, producers and performing-arts organizations \
worldwide. Write concise, respectful B2B outreach emails. Never invent facts, prices or dates \
that are not in the brief. Always include a clear unsubscribe sentence. Reply ONLY with a JSON \
object: {"subject": "...", "body": "..."} where body is plain text with \\n line breaks."""

FALLBACK_TEMPLATES = {
    "en": {
        "subject": "KULISA Talent Network - casting and touring talent for {organization}",
        "body": (
            "Dear {first_name},\n\n"
            "{pitch}\n\n"
            "I would be glad to show you how KULISA can support {organization} specifically.\n\n"
            "Best regards,\n{sender_name}\n\n"
            "You are receiving this because of your professional role at {organization}. "
            "If this is not relevant to you, reply with 'unsubscribe' and you will never be contacted again."
        ),
    },
    "de": {
        "subject": "KULISA Talent Network - Besetzungs- und Tourneetalente für {organization}",
        "body": (
            "Hallo {first_name},\n\n"
            "{pitch}\n\n"
            "Ich zeige Ihnen gerne, wie KULISA {organization} konkret unterstützen kann.\n\n"
            "Mit freundlichen Grüßen,\n{sender_name}\n\n"
            "Sie erhalten diese E-Mail aufgrund Ihrer beruflichen Rolle bei {organization}. "
            "Falls dies nicht relevant ist, antworten Sie mit 'Abbestellen' und wir melden uns nicht mehr."
        ),
    },
    "fr": {
        "subject": "KULISA Talent Network - talents de casting et de tournée pour {organization}",
        "body": (
            "Bonjour {first_name},\n\n"
            "{pitch}\n\n"
            "Je serais ravi de vous montrer comment KULISA peut accompagner {organization}.\n\n"
            "Cordialement,\n{sender_name}\n\n"
            "Vous recevez ce message en raison de votre fonction au sein de {organization}. "
            "Si cela ne vous intéresse pas, répondez « désabonnement » et nous ne vous contacterons plus."
        ),
    },
}


def _fallback(contact: dict, brief: dict) -> dict:
    lang = contact.get("language") or "en"
    tpl = FALLBACK_TEMPLATES.get(lang, FALLBACK_TEMPLATES["en"])
    first = contact.get("first_name") or "Sir or Madam"
    organization = contact.get("organization") or "your organization"
    return {
        "subject": tpl["subject"].format(organization=organization),
        "body": tpl["body"].format(
            first_name=first,
            pitch=brief.get("pitch", "KULISA connects performing-arts organizations with verified, tour-ready talent."),
            sender_name=brief.get("sender_name", "KULISA Talent Network"),
            organization=organization,
        ),
    }


class EmailGenerator:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, contact: dict, brief: dict) -> dict:
        """Return {"subject": ..., "body": ...} personalized for one contact."""
        if not self.settings.mistral_api_key:
            return _fallback(contact, brief)

        language = (contact.get("language") or "en").lower()
        user_prompt = {
            "task": "Write a personalized B2B outreach email.",
            "write_in_language": language,
            "sender": {
                "name": brief.get("sender_name", self.settings.sender_name),
                "email": brief.get("sender_email", self.settings.sender_email),
            },
            "recipient": {
                "first_name": contact.get("first_name"),
                "last_name": contact.get("last_name"),
                "organization": contact.get("organization"),
                "organization_type": contact.get("org_type"),
                "country": contact.get("country"),
            },
            "brief": brief.get("pitch"),
            "call_to_action": brief.get("cta", "a short intro call"),
            "constraints": [
                "max 150 words",
                "professional, warm, no hype",
                "include one unsubscribe sentence",
            ],
        }
        resp = httpx.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.mistral_api_key}"},
            json={
                "model": self.settings.mistral_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
                "temperature": 0.4,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return {"subject": data["subject"].strip(), "body": data["body"].strip()}

    def generate_batch(self, contacts: list[dict], brief: dict, limit: int | None = None) -> list[dict]:
        out = []
        for contact in (contacts[:limit] if limit else contacts):
            email = self.generate(contact, brief)
            out.append({**email, "contact_id": contact["id"], "to": contact["email"]})
        return out
