"""Outbound email abstraction. The `console` backend logs the message (development only)."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from .config import get_settings

log = logging.getLogger("androai_api.mail")


@dataclass
class Mail:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class ConsoleMailer:
    def send(self, mail: Mail) -> None:
        # Development convenience: bodies contain one-time links. Never use in production.
        log.warning("EMAIL to=%s subject=%s\n%s", mail.to, mail.subject, mail.body)


class SmtpMailer:
    def send(self, mail: Mail) -> None:
        s = get_settings()
        if not s.smtp_host:
            raise RuntimeError("SMTP_HOST not configured")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.email_from, mail.to, mail.subject
        msg.set_content(mail.body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password or "")
            smtp.send_message(msg)


@lru_cache
def get_mailer() -> Mailer:
    return SmtpMailer() if get_settings().email_backend == "smtp" else ConsoleMailer()
