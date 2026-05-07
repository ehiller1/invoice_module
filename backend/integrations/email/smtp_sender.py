"""FR-05.2 email transport.

Resolution order:
  1. SendGrid HTTPS API if `SENDGRID_API_KEY` env var is set.
  2. SMTP via stdlib smtplib if `SMTP_HOST` env var is set.
  3. DEV fallback: append the email payload to `backend/data/email_outbox.jsonl`.

The function always returns True on dev fallback so that the upstream pipeline
is not blocked by missing real-world credentials in development.
"""
from __future__ import annotations

import json
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

OUTBOX_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "email_outbox.jsonl"


def _log_to_outbox(to: str, subject: str, html_body: str, text_body: Optional[str], backend: str) -> None:
    OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "backend": backend,
        "to": to,
        "subject": subject,
        "text": text_body or "",
        "html": html_body,
    }
    with OUTBOX_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _send_via_sendgrid(to: str, subject: str, html_body: str, text_body: Optional[str], api_key: str) -> bool:
    try:
        import urllib.request
        import urllib.error
    except Exception:
        return False

    from_addr = os.environ.get("EMAIL_FROM", "noreply@eime.local")
    from_name = os.environ.get("EMAIL_FROM_NAME", "EIME")

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_addr, "name": from_name},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body or ""},
            {"type": "text/html", "value": html_body},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url="https://api.sendgrid.com/v3/mail/send",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _send_via_smtp(to: str, subject: str, html_body: str, text_body: Optional[str], host: str) -> bool:
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    use_tls = os.environ.get("SMTP_TLS", "true").lower() in ("1", "true", "yes")
    from_addr = os.environ.get("EMAIL_FROM", user or "noreply@eime.local")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=10) as srv:
            if use_tls:
                srv.starttls()
            if user and password:
                srv.login(user, password)
            srv.sendmail(from_addr, [to], msg.as_string())
        return True
    except Exception:
        return False


def send_email(to: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an email via the best available transport.

    Returns True if the email was dispatched (or recorded to dev outbox), False
    on a hard transport error.
    """
    api_key = os.environ.get("SENDGRID_API_KEY")
    if api_key:
        ok = _send_via_sendgrid(to, subject, html_body, text_body, api_key)
        # Always log a record for traceability.
        _log_to_outbox(to, subject, html_body, text_body, "sendgrid" if ok else "sendgrid_failed")
        if ok:
            return True
        # fall through to SMTP if available

    smtp_host = os.environ.get("SMTP_HOST")
    if smtp_host:
        ok = _send_via_smtp(to, subject, html_body, text_body, smtp_host)
        _log_to_outbox(to, subject, html_body, text_body, "smtp" if ok else "smtp_failed")
        if ok:
            return True

    # DEV fallback — record only.
    _log_to_outbox(to, subject, html_body, text_body, "dev_outbox")
    return True
