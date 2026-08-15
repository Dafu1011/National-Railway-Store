import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.core.email_sender import send_registration_code_email
from app.core.errors import ErrorCode, error_payload
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


if __name__ == "__main__":
    unittest.main()
