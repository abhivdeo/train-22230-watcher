"""Gmail SMTP notifier."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def send(subject: str, body: str, attach_image: str | None = None) -> None:
    """Send email via Gmail SMTP. Optional image attachment (e.g., screenshot)."""
    user = _require("GMAIL_USER")
    pwd = _require("GMAIL_APP_PASSWORD")
    to = _require("ALERT_EMAIL")

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attach_image and Path(attach_image).exists():
        with open(attach_image, "rb") as f:
            img = MIMEImage(f.read(), name=Path(attach_image).name)
        msg.attach(img)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(user, pwd)
        server.sendmail(user, [to], msg.as_string())
