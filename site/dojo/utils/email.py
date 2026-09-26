import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from socket import timeout

from flask import url_for

from ..config import CTF_NAME, MAIL_ADDRESS, MAIL_PASSWORD, MAIL_PORT, MAIL_SERVER, MAIL_USERNAME
from ..models import get_config
from . import safe_format, serialize

TEMPLATES = {
    "verification_email": (
        "Confirm your account for {ctf_name}",
        "Welcome to {ctf_name}!\n\n"
        "Click the following link to confirm and activate your account:\n"
        "{url}"
        "\n\n"
        "If the link is not clickable, try copying and pasting it into your browser.",
    ),
    "successful_registration_email": (
        "Successfully registered for {ctf_name}",
        "You've successfully registered for {ctf_name}!",
    ),
    "password_reset": (
        "Password Reset Request from {ctf_name}",
        "Did you initiate a password reset on {ctf_name}? "
        "If you didn't initiate this request you can ignore this email. \n\n"
        "Click the following link to reset your password:\n{url}\n\n"
        "If the link is not clickable, try copying and pasting it into your browser.",
    ),
    "password_change_alert": (
        "Password Change Confirmation for {ctf_name}",
        "Your password for {ctf_name} has been changed.\n\n"
        "If you didn't request a password change you can reset your password here:\n{url}\n\n"
        "If the link is not clickable, try copying and pasting it into your browser.",
    ),
}


def can_send_mail():
    return bool(MAIL_SERVER and MAIL_PORT)


def sendmail(addr, text, subject="Message from {ctf_name}"):
    subject = safe_format(subject, ctf_name=CTF_NAME)
    if not can_send_mail():
        return False, "No mail settings configured"
    try:
        smtp_class = smtplib.SMTP_SSL if get_config("mail_ssl") else smtplib.SMTP
        smtp = smtp_class(MAIL_SERVER, int(MAIL_PORT), timeout=3)
        if MAIL_PORT in ("465", "587"):
            smtp.starttls()
        if MAIL_USERNAME:
            smtp.login(MAIL_USERNAME, MAIL_PASSWORD)
        msg = EmailMessage()
        msg.set_content(text)
        msg["Subject"] = subject
        msg["From"] = formataddr((CTF_NAME, MAIL_ADDRESS or "noreply@examplectf.com"))
        msg["To"] = addr
        msg["Date"] = formatdate()
        smtp.send_message(msg)
        smtp.quit()
        return True, "Email sent"
    except smtplib.SMTPException as e:
        return False, str(e)
    except timeout:
        return False, "SMTP server connection timed out"
    except Exception as e:
        return False, str(e)


def notify(kind, addr, url):
    subject, body = TEMPLATES[kind]
    text = safe_format(get_config(f"{kind}_body") or body, ctf_name=CTF_NAME, ctf_description=CTF_NAME, url=url)
    return sendmail(addr=addr, text=text, subject=safe_format(get_config(f"{kind}_subject") or subject, ctf_name=CTF_NAME))


def password_change_alert(email):
    return notify("password_change_alert", email, url_for("auth.reset_password", _external=True))


def forgot_password(email):
    return notify("password_reset", email, url_for("auth.reset_password", data=serialize(email), _external=True))


def verify_email_address(addr):
    return notify("verification_email", addr, url_for("auth.confirm", data=serialize(addr), _external=True, _method="GET"))


def successful_registration_notification(addr):
    return notify("successful_registration_email", addr, url_for("views.static_html", _external=True))


def check_email_is_whitelisted(email_address):
    local_id, _, domain = email_address.partition("@")
    domain_whitelist = get_config("domain_whitelist")
    if domain_whitelist:
        domain_whitelist = [d.strip() for d in domain_whitelist.split(",")]
        for allowed_domain in domain_whitelist:
            if allowed_domain.startswith("*."):
                if "*" in domain:
                    return False
                suffix = allowed_domain[1:]
                if domain.endswith(suffix):
                    return True
            elif domain == allowed_domain:
                return True
        return False
    return True
