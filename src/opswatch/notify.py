"""Alert delivery: SMTP email and Slack-compatible webhooks (stdlib only)."""

from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage


class NotifyError(RuntimeError):
    pass


def build_email(cfg: dict, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    to = cfg["to"]
    msg["To"] = ", ".join(to) if isinstance(to, list) else to
    msg.set_content(body)
    return msg


def send_email(cfg: dict, subject: str, body: str) -> None:
    """Send over SMTP with STARTTLS. The password is read from an environment variable."""
    msg = build_email(cfg, subject, body)
    password_env = cfg.get("password_env")
    password = os.environ.get(password_env, "") if password_env else ""
    if password_env and not password:
        raise NotifyError(f"environment variable {password_env} is not set")
    try:
        with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587)), timeout=15) as smtp:
            smtp.starttls()
            if cfg.get("username"):
                smtp.login(cfg["username"], password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError(f"email failed: {exc}") from exc


def send_webhook(url: str, text: str) -> None:
    """POST {"text": ...}, which Slack, Mattermost and Google Chat webhooks accept."""
    data = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except OSError as exc:
        raise NotifyError(f"webhook failed: {exc}") from exc


def notify_all(notify_cfg: dict, subject: str, body: str) -> list[str]:
    """Send to every configured channel. Returns error messages instead of raising."""
    errors: list[str] = []
    if "email" in notify_cfg:
        try:
            send_email(notify_cfg["email"], subject, body)
        except NotifyError as exc:
            errors.append(str(exc))
    if "webhook" in notify_cfg:
        try:
            send_webhook(notify_cfg["webhook"]["url"], f"{subject}\n{body}")
        except NotifyError as exc:
            errors.append(str(exc))
    return errors
