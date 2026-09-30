from __future__ import annotations

from dataclasses import dataclass
import json
import os
from urllib import request


class SmsNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class SmsConfig:
    provider: str
    access_key_id: str
    access_key_secret: str
    sign_name: str
    template_code: str
    webhook_url: str
    webhook_token: str

    @property
    def configured(self) -> bool:
        if self.provider.lower() == "webhook":
            return bool(self.webhook_url)
        return bool(self.provider and self.access_key_id and self.access_key_secret and self.sign_name and self.template_code)


def load_sms_config() -> SmsConfig:
    return SmsConfig(
        provider=os.getenv("SMS_PROVIDER", "").strip(),
        access_key_id=os.getenv("SMS_ACCESS_KEY_ID", "").strip(),
        access_key_secret=os.getenv("SMS_ACCESS_KEY_SECRET", "").strip(),
        sign_name=os.getenv("SMS_SIGN_NAME", "").strip(),
        template_code=os.getenv("SMS_TEMPLATE_CODE", "").strip(),
        webhook_url=os.getenv("SMS_WEBHOOK_URL", "").strip(),
        webhook_token=os.getenv("SMS_WEBHOOK_TOKEN", "").strip(),
    )


def send_registration_code_sms(phone: str, code: str, *, expires_minutes: int, purpose: str = "register") -> None:
    config = load_sms_config()
    if not config.configured:
        if os.getenv("APP_ENV", "development").strip().lower() == "production":
            raise SmsNotConfigured("SMS_NOT_CONFIGURED")
        return

    if config.provider.lower() != "webhook":
        raise SmsNotConfigured("SMS_PROVIDER_UNSUPPORTED")

    body = json.dumps(
        {
            "phone": phone,
            "code": code,
            "expires_minutes": expires_minutes,
            "purpose": purpose,
            "sign_name": config.sign_name,
            "template_code": config.template_code,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.webhook_token:
        headers["Authorization"] = f"Bearer {config.webhook_token}"
    http_request = request.Request(config.webhook_url, data=body, headers=headers, method="POST")
    with request.urlopen(http_request, timeout=20) as response:
        if response.status >= 400:
            raise SmsNotConfigured("SMS_WEBHOOK_FAILED")
