import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.core.email_sender import send_registration_code_email
from app.core.errors import ErrorCode, error_payload
from app.core.sms_sender import (
    SmsNotConfigured,
    _build_tencent_cloud_api_headers,
    _send_tencent_cloud_api_sms,
    load_sms_config,
    send_registration_code_sms,
)
from app.rendering.barcode.validators import (
    BarcodeType,
    validate_barcode_value,
)
from app.security.ownership import ResourceAccessDenied, assert_owned_by_user, owner_filter


class ErrorPayloadTests(unittest.TestCase):
    def test_error_payload_uses_stable_machine_code_and_request_id(self):
        payload = error_payload(
            ErrorCode.BARCODE_VALUE_INVALID,
            "条形码内容格式错误",
            request_id="req-123",
            details={"field": "barcode"},
        )

        self.assertEqual(payload["code"], "BARCODE_VALUE_INVALID")
        self.assertEqual(payload["message"], "条形码内容格式错误")
        self.assertEqual(payload["request_id"], "req-123")
        self.assertEqual(payload["details"], {"field": "barcode"})


class OwnershipTests(unittest.TestCase):
    def test_owner_filter_always_combines_resource_id_and_user_id(self):
        resource_id = uuid4()
        user_id = uuid4()

        self.assertEqual(owner_filter(resource_id, user_id), {"id": resource_id, "user_id": user_id})

    def test_assert_owned_by_user_blocks_cross_user_access(self):
        with self.assertRaises(ResourceAccessDenied) as raised:
            assert_owned_by_user(resource_user_id=uuid4(), current_user_id=uuid4())

        self.assertEqual(raised.exception.code, "RESOURCE_ACCESS_DENIED")


class BarcodeValidationTests(unittest.TestCase):
    def test_ean13_validates_complete_check_digit(self):
        result = validate_barcode_value(BarcodeType.EAN_13, "4006381333931")

        self.assertTrue(result.length_valid)
        self.assertTrue(result.check_digit_valid)
        self.assertEqual(result.normalized_value, "4006381333931")
        self.assertTrue(result.can_confirm)

    def test_ean13_12_digits_returns_suggestion_without_silent_padding(self):
        result = validate_barcode_value(BarcodeType.EAN_13, "400638133393")

        self.assertTrue(result.length_valid)
        self.assertIsNone(result.check_digit_valid)
        self.assertEqual(result.calculated_check_digit, "1")
        self.assertEqual(result.suggested_full_value, "4006381333931")
        self.assertFalse(result.can_confirm)
        self.assertEqual(result.error_code, "BARCODE_CHECK_DIGIT_SUGGESTED")

    def test_upca_is_not_treated_as_ean13(self):
        result = validate_barcode_value(BarcodeType.UPC_A, "036000291452")

        self.assertEqual(result.barcode_type, BarcodeType.UPC_A)
        self.assertEqual(result.normalized_value, "036000291452")
        self.assertTrue(result.can_confirm)

    def test_code128_rejects_non_digits_in_phase_one(self):
        result = validate_barcode_value(BarcodeType.CODE_128, "ABC123")

        self.assertFalse(result.character_valid)
        self.assertFalse(result.can_confirm)
        self.assertEqual(result.error_code, "BARCODE_VALUE_INVALID")


class EmailSenderTests(unittest.TestCase):
    def test_registration_email_uses_registration_copy_by_default(self):
        message = self._sent_message_for()

        self.assertEqual(message["Subject"], "智枫生图注册验证码")
        self.assertIn("正在注册智枫生图账号", message.get_content())

    def test_password_reset_email_uses_reset_copy(self):
        message = self._sent_message_for(purpose="password_reset")

        self.assertEqual(message["Subject"], "智枫生图密码重置验证码")
        self.assertIn("正在重置智枫生图账号密码", message.get_content())

    def _sent_message_for(self, *, purpose: str = "register"):
        env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "465",
            "SMTP_USERNAME": "sender@example.com",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "sender@example.com",
            "SMTP_USE_SSL": "true",
            "SMTP_USE_TLS": "false",
        }
        with patch.dict(os.environ, env, clear=False), patch("app.core.email_sender.smtplib.SMTP_SSL") as smtp_ssl:
            server = smtp_ssl.return_value.__enter__.return_value
            send_registration_code_email("user@example.com", "123456", expires_minutes=10, purpose=purpose)
            return server.send_message.call_args.args[0]


class SmsSenderTests(unittest.TestCase):
    def test_unconfigured_sms_sender_raises_in_development(self):
        env = {
            "APP_ENV": "development",
            "SMS_PROVIDER": "",
            "SMS_ACCESS_KEY_ID": "",
            "SMS_ACCESS_KEY_SECRET": "",
            "SMS_SIGN_NAME": "",
            "SMS_TEMPLATE_CODE": "",
            "SMS_TENCENT_SECRET_ID": "",
            "SMS_TENCENT_SECRET_KEY": "",
            "SMS_TENCENT_SDK_APP_ID": "",
            "SMS_DEBUG_SKIP_SEND": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(SmsNotConfigured) as raised:
                send_registration_code_sms("13147642018", "123456", expires_minutes=10)

        self.assertEqual(str(raised.exception), "SMS_NOT_CONFIGURED")

    def test_unconfigured_sms_sender_can_skip_in_test_environment(self):
        env = {
            "APP_ENV": "test",
            "SMS_PROVIDER": "",
            "SMS_ACCESS_KEY_ID": "",
            "SMS_ACCESS_KEY_SECRET": "",
            "SMS_SIGN_NAME": "",
            "SMS_TEMPLATE_CODE": "",
            "SMS_TENCENT_SECRET_ID": "",
            "SMS_TENCENT_SECRET_KEY": "",
            "SMS_TENCENT_SDK_APP_ID": "",
            "SMS_DEBUG_SKIP_SEND": "",
        }
        with patch.dict(os.environ, env, clear=False):
            send_registration_code_sms("13147642018", "123456", expires_minutes=10)

    def test_tencent_sms_sender_posts_registration_code_to_send_sms(self):
        http_request = self._sent_tencent_request_for(purpose="register")

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(http_request.full_url, "https://sms.tencentcloudapi.com")
        self.assertEqual(http_request.get_header("X-tc-action"), "SendSms")
        self.assertEqual(http_request.get_header("X-tc-version"), "2021-01-11")
        self.assertEqual(http_request.get_header("X-tc-region"), "ap-guangzhou")
        self.assertTrue(http_request.get_header("Authorization").startswith("TC3-HMAC-SHA256 "))
        self.assertIn("SignedHeaders=content-type;host;x-tc-action", http_request.get_header("Authorization"))
        self.assertEqual(payload["PhoneNumberSet"], ["+8613147642018"])
        self.assertEqual(payload["SmsSdkAppId"], "1401201780")
        self.assertEqual(payload["SignName"], "吉林省智枫信息技术")
        self.assertEqual(payload["TemplateId"], "2653057")
        self.assertEqual(payload["TemplateParamSet"], ["123456", "10"])

    def test_tencent_sms_sender_uses_same_provider_for_password_reset_codes(self):
        http_request = self._sent_tencent_request_for(purpose="password_reset")

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["PhoneNumberSet"], ["+8613147642018"])
        self.assertEqual(payload["TemplateParamSet"], ["123456", "10"])

    def test_tencent_sms_sender_supports_code_only_template_param_mode(self):
        http_request = self._sent_tencent_request_for(
            purpose="register",
            overrides={"SMS_TEMPLATE_PARAM_MODE": "code_only"},
        )

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["TemplateParamSet"], ["123456"])

    def test_tencent_sms_sender_uses_password_reset_template_code_override(self):
        http_request = self._sent_tencent_request_for(
            purpose="password_reset",
            overrides={
                "SMS_PASSWORD_RESET_SIGN_NAME": "WrongSign",
                "SMS_PASSWORD_RESET_TEMPLATE_CODE": "888888",
                "SMS_PASSWORD_RESET_TEMPLATE_PARAM_MODE": "code_only",
            },
        )

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["SignName"], "吉林省智枫信息技术")
        self.assertEqual(payload["TemplateId"], "888888")
        self.assertEqual(payload["TemplateParamSet"], ["123456"])

    def test_tencent_sms_sender_uses_shared_registration_template_code(self):
        http_request = self._sent_tencent_request_for(
            purpose="register",
            overrides={
                "SMS_REGISTER_SIGN_NAME": "WrongSign",
                "SMS_REGISTER_TEMPLATE_CODE": "777777",
                "SMS_REGISTER_TEMPLATE_PARAM_MODE": "code_only",
            },
        )

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["SignName"], "吉林省智枫信息技术")
        self.assertEqual(payload["TemplateId"], "2653057")
        self.assertEqual(payload["TemplateParamSet"], ["123456", "10"])

    def test_tencent_sms_sender_supports_explicit_tencent_secret_fields(self):
        http_request = self._sent_tencent_request_for(
            purpose="register",
            overrides={
                "SMS_ACCESS_KEY_ID": "",
                "SMS_ACCESS_KEY_SECRET": "",
                "SMS_TENCENT_SECRET_ID": "AKIDEXAMPLE",
                "SMS_TENCENT_SECRET_KEY": "secret",
            },
        )

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["SmsSdkAppId"], "1401201780")
        self.assertTrue(http_request.get_header("Authorization").startswith("TC3-HMAC-SHA256 "))

    def test_tencent_sms_sender_supports_numeric_sdk_app_id_legacy_config(self):
        env = {
            "SMS_PROVIDER": "tencent",
            "SMS_ACCESS_KEY_ID": "1401201780",
            "SMS_ACCESS_KEY_SECRET": "app-key-secret",
            "SMS_SIGN_NAME": "吉林省智枫信息技术",
            "SMS_TEMPLATE_CODE": "2653057",
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"result": 0, "errmsg": "OK", "sid": "sid-1"}).encode("utf-8")

        with patch.dict(os.environ, env, clear=False), patch("app.core.sms_sender.request.urlopen") as urlopen:
            urlopen.return_value = FakeResponse()
            send_registration_code_sms("13147642018", "123456", expires_minutes=10)
            http_request = urlopen.call_args.args[0]

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertTrue(http_request.full_url.startswith("https://yun.tim.qq.com/v5/tlssmssvr/sendsms"))
        self.assertIn("sdkappid=1401201780", http_request.full_url)
        self.assertEqual(payload["tel"], {"nationcode": "86", "mobile": "13147642018"})
        self.assertEqual(payload["tpl_id"], 2653057)
        self.assertEqual(payload["params"], ["123456", "10"])
        self.assertEqual(payload["sign"], "吉林省智枫信息技术")
        self.assertEqual(len(payload["sig"]), 64)

    def test_tencent_legacy_sms_sender_supports_code_only_template_param_mode(self):
        env = {
            "SMS_PROVIDER": "tencent",
            "SMS_ACCESS_KEY_ID": "1401201780",
            "SMS_ACCESS_KEY_SECRET": "app-key-secret",
            "SMS_SIGN_NAME": "吉林省智枫信息技术",
            "SMS_TEMPLATE_CODE": "2653057",
            "SMS_TEMPLATE_PARAM_MODE": "code_only",
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"result": 0, "errmsg": "OK", "sid": "sid-1"}).encode("utf-8")

        with patch.dict(os.environ, env, clear=False), patch("app.core.sms_sender.request.urlopen") as urlopen:
            urlopen.return_value = FakeResponse()
            send_registration_code_sms("13147642018", "123456", expires_minutes=10)
            http_request = urlopen.call_args.args[0]

        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["params"], ["123456"])


    def test_tencent_sms_sender_requires_sdk_app_id(self):
        env = {
            "SMS_PROVIDER": "tencent",
            "SMS_ACCESS_KEY_ID": "AKIDEXAMPLE",
            "SMS_ACCESS_KEY_SECRET": "secret",
            "SMS_SIGN_NAME": "吉林省智枫信息技术",
            "SMS_TEMPLATE_CODE": "2653057",
            "SMS_TENCENT_SDK_APP_ID": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(SmsNotConfigured) as raised:
                send_registration_code_sms("13147642018", "123456", expires_minutes=10)

        self.assertEqual(str(raised.exception), "SMS_TENCENT_NOT_CONFIGURED")

    def test_tencent_sms_sender_rejects_cloud_api_error_response(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "Response": {
                            "Error": {
                                "Code": "AuthFailure.SignatureFailure",
                                "Message": "The provided credentials could not be validated.",
                            },
                            "RequestId": "request-1",
                        }
                    }
                ).encode("utf-8")

        env = {
            "SMS_PROVIDER": "tencent",
            "SMS_ACCESS_KEY_ID": "AKIDEXAMPLE",
            "SMS_ACCESS_KEY_SECRET": "secret",
            "SMS_SIGN_NAME": "吉林省智枫信息技术",
            "SMS_TEMPLATE_CODE": "2653057",
            "SMS_TENCENT_SDK_APP_ID": "1401201780",
        }
        with patch.dict(os.environ, env, clear=False), patch("app.core.sms_sender.request.urlopen") as urlopen:
            urlopen.return_value = FakeResponse()
            with self.assertRaises(SmsNotConfigured) as raised:
                send_registration_code_sms("13147642018", "123456", expires_minutes=10)

        self.assertIn("AuthFailure.SignatureFailure", str(raised.exception))

    def test_tencent_cloud_signature_canonicalizes_action_header_value_to_lowercase(self):
        body = "{}"
        with patch("app.core.sms_sender.time.time", return_value=1_800_000_000):
            send_sms_headers = _build_tencent_cloud_api_headers(
                secret_id="AKIDEXAMPLE",
                secret_key="secret",
                endpoint="sms.tencentcloudapi.com",
                action="SendSms",
                region="ap-guangzhou",
                version="2021-01-11",
                body=body,
            )
            lower_action_headers = _build_tencent_cloud_api_headers(
                secret_id="AKIDEXAMPLE",
                secret_key="secret",
                endpoint="sms.tencentcloudapi.com",
                action="sendsms",
                region="ap-guangzhou",
                version="2021-01-11",
                body=body,
            )

        self.assertEqual(send_sms_headers["Authorization"], lower_action_headers["Authorization"])

    def test_tencent_cloud_sms_prefers_official_sdk_sender_when_available(self):
        env = {
            "SMS_PROVIDER": "tencent",
            "SMS_ACCESS_KEY_ID": "AKIDEXAMPLE",
            "SMS_ACCESS_KEY_SECRET": "secret",
            "SMS_SIGN_NAME": "吉林省智枫信息技术",
            "SMS_TEMPLATE_CODE": "2653057",
            "SMS_TENCENT_SDK_APP_ID": "1401201780",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "app.core.sms_sender._send_tencent_cloud_sdk_sms", return_value=True
        ) as sdk_sender, patch("app.core.sms_sender.request.urlopen") as urlopen:
            _send_tencent_cloud_api_sms(load_sms_config(), "13147642018", "123456", expires_minutes=10, purpose="register")

        sdk_sender.assert_called_once()
        urlopen.assert_not_called()

    def _sent_tencent_request_for(self, *, purpose: str, overrides: dict[str, str] | None = None):
        env = {
            "SMS_PROVIDER": "tencent",
            "SMS_ACCESS_KEY_ID": "AKIDEXAMPLE",
            "SMS_ACCESS_KEY_SECRET": "secret",
            "SMS_SIGN_NAME": "吉林省智枫信息技术",
            "SMS_TEMPLATE_CODE": "2653057",
            "SMS_TENCENT_SDK_APP_ID": "1401201780",
            "SMS_TENCENT_REGION": "ap-guangzhou",
        }
        env.update(overrides or {})

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "Response": {
                            "RequestId": "request-1",
                            "SendStatusSet": [{"Code": "Ok", "Message": "send success"}],
                        }
                    }
                ).encode("utf-8")

        with patch.dict(os.environ, env, clear=False), patch(
            "app.core.sms_sender._send_tencent_cloud_sdk_sms", return_value=False
        ), patch("app.core.sms_sender.request.urlopen") as urlopen:
            urlopen.return_value = FakeResponse()
            send_registration_code_sms("13147642018", "123456", expires_minutes=10, purpose=purpose)
            return urlopen.call_args.args[0]


if __name__ == "__main__":
    unittest.main()
