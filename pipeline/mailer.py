"""Mailbox SMTP send — same pattern as test_smtp.py (SMTP_SSL :465, login from .env).

    import mailer
    mailer.send(to, subject, text, html=None, attachments=[Path(...), ...])

Used by the nightly report (HTML + PDF form records) and by follow-ups (plain
text). Raises on failure — callers log it; nothing here prints credentials.
"""

import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

import db

MAX_ATTACH_BYTES = 8_000_000     # most providers cap around 25MB; keep the report mailbox-friendly


def build(to, subject, text, html=None, attachments=(), reply_to=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{db.applicant_name()} <{db.ENV['MAIL_ADDRESS']}>"
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=db.ENV["MAIL_ADDRESS"].split("@")[-1])
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    total = 0
    skipped = []
    for p in attachments:
        p = Path(p)
        try:
            data = p.read_bytes()
        except OSError:
            skipped.append(p.name)
            continue
        if total + len(data) > MAX_ATTACH_BYTES:
            skipped.append(p.name)
            continue
        total += len(data)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)
    return msg, skipped


def send(to, subject, text, html=None, attachments=(), reply_to=None):
    """Send one message. Returns the list of attachments that did not fit."""
    msg, skipped = build(to, subject, text, html, attachments, reply_to)
    s = smtplib.SMTP_SSL(db.ENV["MAIL_SMTP_HOST"], int(db.ENV["MAIL_SMTP_PORT"]),
                         context=ssl.create_default_context(), timeout=30)
    try:
        s.login(db.ENV["MAIL_ADDRESS"], db.ENV["MAIL_PASSWORD"])
        s.send_message(msg)
    finally:
        s.quit()
    return skipped
