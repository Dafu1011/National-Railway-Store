from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import random
import time
from urllib import request
from urllib.parse import urlencode


class SmsNotConfigured(RuntimeError):
    pass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmsConfig:
    provider: str
    access_key_id: str
    access_key_secret: str
    sign_name: str
    template_code: str
    webhook_url: str
    webhook_token: str
    tencent_sdk_app_id: str
    tencent_secret_id: str
    tencent_secret_key: str
    tencent_region: str
    tencent_endpoint: str
    tencent_version: str

    @property
    def configured(self) -> bool:
        return _sms_configured_for_purpose(self, "register")


def _sms_configured_for_purpose(config: SmsConfig, purpose: str) -> bool:
    sign_name = _sign_name_for_purpose(config, purpose)
    template_code = _template_code_for_purpose(config, purpose)
    provider = config.provider.lower()
    if provider == "webhook":
        return bool(config.webhook_url)
    if provider == "tencent":
        legacy_configured = bool(
            config.access_key_id
            and config.access_key_id.isdigit()
            and config.access_key_secret
            and sign_name
            and template_code
        )
        cloud_api_configured = bool(
            (config.tencent_secret_id or config.access_key_id)
            and (config.tencent_secret_key or config.access_key_secret)
            and config.tencent_sdk_app_id
            and sign_name
            and template_code
        )
        return legacy_configured or cloud_api_configured
    return bool(config.provider and config.access_key_id and config.access_key_secret and sign_name and template_code)


def _purpose_env_prefix(purpose: str) -> str | None:
    if purpose == "password_reset":
        return "SMS_PASSWORD_RESET"
    return None


def _purpose_env_value(purpose: str, suffix: str) -> str:
    prefix = _purpose_env_prefix(purpose)
    if not prefix:
        return ""
    return os.getenv(f"{prefix}_{suffix}", "").strip()


def _sign_name_for_purpose(config: SmsConfig, purpose: str) -> str:
    return config.sign_name


def _template_code_for_purpose(config: SmsConfig, purpose: str) -> str:
    return _purpose_env_value(purpose, "TEMPLATE_CODE") or config.template_code


def _template_param_mode_for_purpose(purpose: str) -> str:
    return (
        _purpose_env_value(purpose, "TEMPLATE_PARAM_MODE")
        or os.getenv("SMS_TEMPLATE_PARAM_MODE", "code_expire").strip()
    ).lower()


def load_sms_config() -> SmsConfig:
    return SmsConfig(
        provider=os.getenv("SMS_PROVIDER", "").strip(),
        access_key_id=os.getenv("SMS_ACCESS_KEY_ID", "").strip(),
        access_key_secret=os.getenv("SMS_ACCESS_KEY_SECRET", "").strip(),
        sign_name=os.getenv("SMS_SIGN_NAME", "").strip(),
        template_code=os.getenv("SMS_TEMPLATE_CODE", "").strip(),
        webhook_url=os.getenv("SMS_WEBHOOK_URL", "").strip(),
        webhook_token=os.getenv("SMS_WEBHOOK_TOKEN", "").strip(),
        tencent_sdk_app_id=os.getenv("SMS_TENCENT_SDK_APP_ID", "").strip(),
        tencent_secret_id=os.getenv("SMS_TENCENT_SECRET_ID", "").strip(),
        tencent_secret_key=os.getenv("SMS_TENCENT_SECRET_KEY", "").strip(),
        tencent_region=os.getenv("SMS_TENCENT_REGION", "ap-guangzhou").strip(),
        tencent_endpoint=os.getenv("SMS_TENCENT_ENDPOINT", "sms.tencentcloudapi.com").strip(),
        tencent_version=os.getenv("SMS_TENCENT_VERSION", "2021-01-11").strip(),
    )


def send_registration_code_sms(phone: str, code: str, *, expires_minutes: int, purpose: str = "register") -> None:
    config = load_sms_config()
    provider = config.provider.lower()
    if not _sms_configured_for_purpose(config, purpose):
        if provider == "tencent":
            raise SmsNotConfigured("SMS_TENCENT_NOT_CONFIGURED")
        if _allow_unconfigured_sms_skip():
            return
        raise SmsNotConfigured("SMS_NOT_CONFIGURED")

    if provider == "tencent":
        _send_tencent_sms(config, phone, code, expires_minutes=expires_minutes, purpose=purpose)
        return

    if provider != "webhook":
        raise SmsNotConfigured("SMS_PROVIDER_UNSUPPORTED")

    body = json.dumps(
        {
            "phone": phone,
            "code": code,
            "expires_minutes": expires_minutes,
            "purpose": purpose,
            "sign_name": _sign_name_for_purpose(config, purpose),
            "template_code": _template_code_for_purpose(config, purpose),
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.webhook_token:
        headers["Authorization"] = f"Bearer {config.webhook_token}"
    http_request = request.Request(config.webhook_url, data=body, headers=headers, method="POST")
    with request.urlopen(http_request, timeout=20) as response:
        if response.status >= 400:
            raise SmsNotConfigured("SMS_WEBHOOK_FAILED")


def _send_tencent_sms(config: SmsConfig, phone: str, code: str, *, expires_minutes: int, purpose: str) -> None:
    if _looks_like_tencent_legacy_config(config):
        _send_tencent_legacy_sms(config, phone, code, expires_minutes=expires_minutes, purpose=purpose)
        return
    _send_tencent_cloud_api_sms(config, phone, code, expires_minutes=expires_minutes, purpose=purpose)


def _looks_like_tencent_legacy_config(config: SmsConfig) -> bool:
    if config.tencent_secret_id or config.access_key_id.upper().startswith("AKID"):
        return False
    return bool(config.access_key_id and config.access_key_id.isdigit())


def _send_tencent_legacy_sms(
    config: SmsConfig,
    phone: str,
    code: str,
    *,
    expires_minutes: int,
    purpose: str,
) -> None:
    sign_name = _sign_name_for_purpose(config, purpose)
    template_code = _template_code_for_purpose(config, purpose)
    if not (config.access_key_id and config.access_key_secret and sign_name and template_code):
        raise SmsNotConfigured("SMS_TENCENT_NOT_CONFIGURED")
    try:
        template_id = int(template_code)
    except ValueError as exc:
        raise SmsNotConfigured("SMS_TENCENT_NOT_CONFIGURED") from exc

    timestamp = int(time.time())
    random_value = random.randint(100000, 999999999)
    normalized_phone = _normalize_mainland_phone(phone)
    signature_source = (
        f"appkey={config.access_key_secret}&random={random_value}&time={timestamp}&mobile={normalized_phone}"
    )
    body = {
        "tel": {"nationcode": "86", "mobile": normalized_phone},
        "sign": sign_name,
        "tpl_id": template_id,
        "params": _template_params(code, expires_minutes, purpose=purpose),
        "sig": hashlib.sha256(signature_source.encode("utf-8")).hexdigest(),
        "time": timestamp,
        "extend": "",
        "ext": purpose,
    }
    url = "https://yun.tim.qq.com/v5/tlssmssvr/sendsms?" + urlencode(
        {"sdkappid": config.access_key_id, "random": random_value}
    )
    http_request = request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(http_request, timeout=20) as response:
        payload = _read_json_response(response)
        if response.status >= 400 or int(payload.get("result", -1)) != 0:
            raise SmsNotConfigured(f"SMS_TENCENT_FAILED:{payload.get('errmsg', 'unknown')}")


def _send_tencent_cloud_api_sms(
    config: SmsConfig,
    phone: str,
    code: str,
    *,
    expires_minutes: int,
    purpose: str,
) -> None:
    secret_id = config.tencent_secret_id or config.access_key_id
    secret_key = config.tencent_secret_key or config.access_key_secret
    sdk_app_id = config.tencent_sdk_app_id
    sign_name = _sign_name_for_purpose(config, purpose)
    template_code = _template_code_for_purpose(config, purpose)
    if _looks_like_tencent_legacy_config(config):
        sdk_app_id = sdk_app_id or config.access_key_id
    if not (
        secret_id
        and secret_key
        and sdk_app_id
        and sign_name
        and template_code
        and config.tencent_endpoint
        and config.tencent_version
    ):
        raise SmsNotConfigured("SMS_TENCENT_NOT_CONFIGURED")

    logger.info(
        "Tencent SMS cloud config provider=tencent secret_id=%s secret_key_length=%s sdk_app_id=%s region=%s endpoint=%s version=%s sdk_available=%s",
        _mask_secret_id(secret_id),
        len(secret_key),
        sdk_app_id,
        config.tencent_region,
        config.tencent_endpoint,
        config.tencent_version,
        _tencent_cloud_sdk_available(),
    )
    if _send_tencent_cloud_sdk_sms(config, phone, code, expires_minutes=expires_minutes, purpose=purpose):
        logger.info("Tencent SMS sent through official SDK path purpose=%s", purpose)
        return

    logger.warning("Tencent SMS official SDK unavailable; falling back to manual TC3 signature path purpose=%s", purpose)
    body = json.dumps(
        {
            "PhoneNumberSet": [_normalize_e164_phone(phone)],
            "SmsSdkAppId": sdk_app_id,
            "SignName": sign_name,
            "TemplateId": template_code,
            "TemplateParamSet": _template_params(code, expires_minutes, purpose=purpose),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    headers = _build_tencent_cloud_api_headers(
        secret_id=secret_id,
        secret_key=secret_key,
        endpoint=config.tencent_endpoint,
        action="SendSms",
        region=config.tencent_region,
        version=config.tencent_version,
        body=body,
    )
    url = f"https://{config.tencent_endpoint}"
    http_request = request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    with request.urlopen(http_request, timeout=20) as response:
        payload = _read_json_response(response)
        response_payload = payload.get("Response", {})
        if not isinstance(response_payload, dict):
            raise SmsNotConfigured("SMS_TENCENT_INVALID_RESPONSE")
        error_payload = response_payload.get("Error")
        if isinstance(error_payload, dict):
            code_value = error_payload.get("Code", "Unknown")
            message = error_payload.get("Message", "unknown")
            raise SmsNotConfigured(f"SMS_TENCENT_FAILED:{code_value}:{message}")
        statuses = response_payload.get("SendStatusSet", [])
        if not isinstance(statuses, list) or not statuses:
            raise SmsNotConfigured("SMS_TENCENT_INVALID_RESPONSE")
        failed_status = next((status for status in statuses if status.get("Code") != "Ok"), None)
        if response.status >= 400 or failed_status is not None:
            message = failed_status.get("Message", "unknown") if failed_status else "unknown"
            raise SmsNotConfigured(f"SMS_TENCENT_FAILED:{message}")


def _build_tencent_cloud_api_headers(
    *,
    secret_id: str,
    secret_key: str,
    endpoint: str,
    action: str,
    region: str,
    version: str,
    body: str,
) -> dict[str, str]:
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    service = endpoint.split(".", 1)[0]
    content_type = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{content_type}\nhost:{endpoint}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(body.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, hashed_request_payload]
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": endpoint,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
    }
    if region:
        headers["X-TC-Region"] = region
    return headers


def _send_tencent_cloud_sdk_sms(
    config: SmsConfig,
    phone: str,
    code: str,
    *,
    expires_minutes: int,
    purpose: str,
) -> bool:
    try:
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.sms.v20210111 import models, sms_client
    except ModuleNotFoundError:
        return False

    secret_id = config.tencent_secret_id or config.access_key_id
    secret_key = config.tencent_secret_key or config.access_key_secret
    sign_name = _sign_name_for_purpose(config, purpose)
    template_code = _template_code_for_purpose(config, purpose)
    request_payload = {
        "PhoneNumberSet": [_normalize_e164_phone(phone)],
        "SmsSdkAppId": config.tencent_sdk_app_id,
        "SignName": sign_name,
        "TemplateId": template_code,
        "TemplateParamSet": _template_params(code, expires_minutes, purpose=purpose),
    }
    http_profile = HttpProfile()
    http_profile.endpoint = config.tencent_endpoint
    client_profile = ClientProfile()
    client_profile.signMethod = "TC3-HMAC-SHA256"
    client_profile.httpProfile = http_profile
    client = sms_client.SmsClient(
        credential.Credential(secret_id, secret_key),
        config.tencent_region,
        client_profile,
    )
    sdk_request = models.SendSmsRequest()
    sdk_request.from_json_string(json.dumps(request_payload, ensure_ascii=False))
    try:
        sdk_response = client.SendSms(sdk_request)
    except TencentCloudSDKException as exc:
        raise SmsNotConfigured(f"SMS_TENCENT_FAILED:{exc.code}:{exc.message}") from exc
    response_payload = json.loads(sdk_response.to_json_string())
    statuses = response_payload.get("SendStatusSet", [])
    if not isinstance(statuses, list) or not statuses:
        raise SmsNotConfigured("SMS_TENCENT_INVALID_RESPONSE")
    failed_status = next((status for status in statuses if status.get("Code") != "Ok"), None)
    if failed_status is not None:
        raise SmsNotConfigured(f"SMS_TENCENT_FAILED:{failed_status.get('Code', 'Unknown')}:{failed_status.get('Message', 'unknown')}")
    return True


def _tencent_cloud_sdk_available() -> bool:
    try:
        import tencentcloud  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def _mask_secret_id(secret_id: str) -> str:
    if len(secret_id) <= 12:
        return "***"
    return f"{secret_id[:8]}...{secret_id[-4:]}"


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _template_params(code: str, expires_minutes: int, *, purpose: str) -> list[str]:
    mode = _template_param_mode_for_purpose(purpose)
    if mode in {"code_only", "code"}:
        return [code]
    return [code, str(expires_minutes)]


def _allow_unconfigured_sms_skip() -> bool:
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    debug_skip = os.getenv("SMS_DEBUG_SKIP_SEND", "").strip().lower()
    return app_env in {"test", "local"} or debug_skip in {"1", "true", "yes", "on"}


def _normalize_e164_phone(phone: str) -> str:
    normalized = phone.strip().replace(" ", "").replace("-", "")
    if normalized.startswith("+"):
        return normalized
    if normalized.startswith("86") and len(normalized) == 13:
        return f"+{normalized}"
    return f"+86{normalized}"


def _normalize_mainland_phone(phone: str) -> str:
    normalized = phone.strip().replace(" ", "").replace("-", "")
    if normalized.startswith("+86"):
        return normalized[3:]
    if normalized.startswith("86") and len(normalized) == 13:
        return normalized[2:]
    return normalized


def _read_json_response(response: object) -> dict[str, object]:
    raw_body = response.read().decode("utf-8")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise SmsNotConfigured("SMS_TENCENT_INVALID_RESPONSE") from exc
    if not isinstance(payload, dict):
        raise SmsNotConfigured("SMS_TENCENT_INVALID_RESPONSE")
    return payload
