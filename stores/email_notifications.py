"""Reusable SMTP email notifications for PacIOOS scripts."""
from __future__ import annotations

import os
import smtplib
import ssl
import sys
import time
import traceback
from email.message import EmailMessage
from pathlib import Path
from typing import Sequence


# TODO: maybe setup logging to be reused across the porject
def log(*a) -> None:
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def parse_recipient_list(to_addresses: str | Sequence[str]) -> list[str]:
    values = to_addresses.split(',') if isinstance(to_addresses, str) else to_addresses
    recipients = [address.strip() for address in values]
    if not recipients or any(
            (
                not address
                or '@' not in address
                or '\r' in address
                or '\n' in address
            ) for address in recipients
        ):
        raise ValueError('to_addresses must contain valid email addresses')
    return recipients


def email_error(
    script_filepath: str | Path,
    error: BaseException,
    to_addresses: str | Sequence[str] | None = None,
    from_address: str | None = None,
    reply_to_address: str | None = None,
    subject_add: str | None = None,
    message_add: str | None = None,
    print_error: bool = False,
) -> None:
    """Send exception details by SMTP.

    Requires recipients via `to_addresses` or PACIOOS_ALERT_EMAIL_TO, PACIOOS_SMTP_HOST, and
    a sender via `from_address` or PACIOOS_ALERT_EMAIL_FROM. SMTP port and security default to
    587/STARTTLS; set PACIOOS_SMTP_PORT or PACIOOS_SMTP_SECURITY to override. Set
    PACIOOS_SMTP_USERNAME and PACIOOS_SMTP_PASSWORD together to authenticate.
    """
    if to_addresses is None:
        to_addresses = os.environ.get('PACIOOS_ALERT_EMAIL_TO')
    if not to_addresses:
        raise ValueError('set to_addresses or PACIOOS_ALERT_EMAIL_TO')
    recipients = parse_recipient_list(to_addresses)
    sender = from_address or os.environ.get('PACIOOS_ALERT_EMAIL_FROM')
    if not sender:
        raise ValueError('set from_address or PACIOOS_ALERT_EMAIL_FROM')
    if '\r' in sender or '\n' in sender:
        raise ValueError('from_address must be one email address')

    host = os.environ.get('PACIOOS_SMTP_HOST')
    if not host:
        raise ValueError('PACIOOS_SMTP_HOST is required')
    security = os.environ.get('PACIOOS_SMTP_SECURITY', 'starttls').lower()
    if security not in ('starttls', 'ssl'):
        raise ValueError('PACIOOS_SMTP_SECURITY must be "starttls" or "ssl"')
    default_port = '465' if security == 'ssl' else '587'
    port = int(os.environ.get('PACIOOS_SMTP_PORT', default_port))

    username = os.environ.get('PACIOOS_SMTP_USERNAME')
    password = os.environ.get('PACIOOS_SMTP_PASSWORD')
    if bool(username) != bool(password):
        raise ValueError('set both PACIOOS_SMTP_USERNAME and PACIOOS_SMTP_PASSWORD, or neither')

    message = EmailMessage()
    message['From'] = sender
    message['To'] = ', '.join(recipients)

    subject = f'{Path(script_filepath).name}: ERROR!'
    if subject_add:
        subject += f' {subject_add}'
    message['Subject'] = subject

    if reply_to_address:
        message['Reply-To'] = reply_to_address

    body = f'{message_add}\n\n' if message_add else ''
    body += f'{type(error).__name__}: {error}\n\nTraceback info:\n'
    body += ''.join(traceback.format_exception(error))
    message.set_content(body)

    if print_error:
        print(error)
        traceback.print_tb(error.__traceback__, file=sys.stdout)

    smtp_class = smtplib.SMTP_SSL if security == 'ssl' else smtplib.SMTP
    smtp_options = {'timeout': 30}
    if security == 'ssl':
        smtp_options['context'] = ssl.create_default_context()

    with smtp_class(host, port, **smtp_options) as smtp:
        if security == 'starttls':
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if username:
            smtp.login(username, password)
        smtp.send_message(message, from_addr=sender, to_addrs=recipients)


def try_email_error(
    script_filepath: str | Path,
    error: BaseException,
    to_addresses: str | Sequence[str] | None = None,
    from_address: str | None = None,
    reply_to_address: str | None = None,
    subject_add: str | None = None,
    message_add: str | None = None,
    print_error: bool = False,
) -> None:
    """Try sending an error email; log configuration or delivery failures instead of raising."""
    try:
        email_error(
            script_filepath=script_filepath,
            error=error,
            to_addresses=to_addresses,
            from_address=from_address,
            reply_to_address=reply_to_address,
            subject_add=subject_add,
            message_add=message_add,
            print_error=print_error,
        )
    except BaseException as mail_error:  # noqa: BLE001
        log(f'error email delivery failed: {type(mail_error).__name__}: {mail_error}')
