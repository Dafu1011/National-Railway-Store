from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import os
import smtplib
import ssl


class EmailNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class EmailConfig:
    host: str
    port: int
    username: str
    password: str
    from_address: str
    use_ssl: bool
    use_tls: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.password and self.from_address)


def load_email_config() -> EmailConfig:
    return EmailConfig(
        host=os.getenv("SMTP_HOST", "").strip(),
        port=int(os.getenv("SMTP_PORT", "465")),
        username=os.getenv("SMTP_USERNAME", "").strip(),
        password=os.getenv("SMTP_PASSWORD", "").strip(),
        from_address=os.getenv("SMTP_FROM", "").strip(),
        use_ssl=os.getenv("SMTP_USE_SSL", "true").strip().lower() in {"1", "true", "yes"},
        use_tls=os.getenv("SMTP_USE_TLS", "false").strip().lower() in {"1", "true", "yes"},
    )


def send_registration_code_email(email: str, code: str, *, expires_minutes: int, purpose: str = "register") -> None:
    config = load_email_config()
    if not config.configured:
        if os.getenv("APP_ENV", "development").strip().lower() == "production":
            raise EmailNotConfigured("SMTP_NOT_CONFIGURED")
        return

    if purpose == "password_reset":
        subject = "智枫生图密码重置验证码"
        action_line = f"您正在重置智枫生图账号密码，验证码为：{code}"
    else:
        subject = "智枫生图注册验证码"
        action_line = f"您正在注册智枫生图账号，验证码为：{code}"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                "您好，",
                "",
                action_line,
                f"验证码 {expires_minutes} 分钟内有效，请勿转发给他人。",
                "",
                "如果不是您本人操作，请忽略本邮件。",
            ]
        )
    )

    context = ssl.create_default_context()
    if config.use_ssl:
        with smtplib.SMTP_SSL(config.host, config.port, context=context, timeout=20) as server:
            server.login(config.username, config.password)
            server.send_message(message)
        return

    with smtplib.SMTP(config.host, config.port, timeout=20) as server:
        if config.use_tls:
            server.starttls(context=context)
        server.login(config.username, config.password)
        server.send_message(message)
