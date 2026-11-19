"""Best-effort SMTP alerts containing job summaries and explicitly safe recovery guidance."""
from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
import ssl
import stat
import sys

from layout import managed_path


def read_password(filename):
    filename = Path(filename)
    info = filename.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('SMTP password must be a regular file owned by the current user')
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('SMTP password file must not be accessible by group or others (use chmod 600)')
    password = filename.read_text().rstrip('\r\n')
    if not password or '\r' in password or '\n' in password:
        raise ValueError('SMTP password file is empty or contains line breaks')
    return password


def configured_password(cfg, settings, username):
    password_file = settings.get('smtp_password_file')
    if password_file is None:
        if username:
            raise ValueError('Configure both smtp_username and smtp_password_file, or neither')
        return None
    if not isinstance(password_file, str) or not password_file:
        raise ValueError('smtp_password_file must be a non-empty path')
    if not username:
        raise ValueError('Configure both smtp_username and smtp_password_file, or neither')
    password_file = managed_path(cfg['install_root'], password_file, 'SMTP password file')
    if '\n' in password_file or '%' in password_file:
        raise ValueError('SMTP password file path cannot contain newline or %')
    return read_password(password_file)


def send_message(cfg, subject, body):
    settings = cfg.get('notifications', {})
    if not isinstance(settings, dict):
        raise ValueError('notifications must be a TOML table')
    recipients = settings.get('to_addresses')
    sender = settings.get('from_address', '')
    if (not isinstance(recipients, list) or not recipients
            or any(not isinstance(value, str) or not value.strip() for value in recipients)):
        raise ValueError('Configure one or more notification to_addresses')
    recipients = [value.strip() for value in recipients]
    if (not isinstance(sender, str)
            or any(not value or '@' not in value or '\r' in value or '\n' in value
                   for value in [sender, *recipients])):
        raise ValueError('Configure valid alert sender and recipients')
    host = settings.get('smtp_host')
    if not isinstance(host, str) or not host.strip() or host != host.strip() or '\r' in host or '\n' in host:
        raise ValueError('Configure a valid notifications.smtp_host')
    security = settings.get('smtp_security', 'starttls')
    if not isinstance(security, str):
        raise ValueError('SMTP security must be starttls or ssl')
    security = security.lower()
    if security not in ('starttls', 'ssl'):
        raise ValueError('SMTP security must be starttls or ssl')
    port = settings.get('smtp_port', 465 if security == 'ssl' else 587)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('SMTP port must be an integer from 1 to 65535')
    username = settings.get('smtp_username')
    if username is not None and (not isinstance(username, str) or not username.strip()
                                 or '\r' in username or '\n' in username):
        raise ValueError('SMTP username must be a non-empty string without line breaks')
    password = configured_password(cfg, settings, username)

    message = EmailMessage()
    message['From'] = sender
    message['To'] = ', '.join(recipients)
    message['Subject'] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if security == 'ssl' else smtplib.SMTP
    options = dict(timeout=30, **({'context': context} if security == 'ssl' else {}))
    with smtp_class(host, port, **options) as smtp:
        if security == 'starttls':
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if username:
            smtp.login(username, password)
        refused = smtp.send_message(message, from_addr=sender, to_addrs=recipients)
        if refused:
            raise RuntimeError('Some alert recipients were refused')


def notify_failures(cfg, action, scope, failures, logs, details=None):
    """Isolate delivery/configuration failures from job results and recovery state."""
    try:
        label = f'{action} (scope: {scope})'
        rows = [f'Icechunker {label} failed.', '', 'Failures:']
        for name, status in failures:
            detail = (details or {}).get(name, {})
            rows.append(f'{name}: {status}')
            if detail.get('error_type'):
                rows.append(f'Error: {detail["error_type"]}')
            if detail.get('location'):
                rows.append(f'Location: {detail["location"]}')
            if detail.get('message'):
                rows.append(f'Reason: {detail["message"]}')
            if detail.get('unavailable'):
                rows.append('Failure details unavailable for this worker run.')
            if detail.get('log_path'):
                rows.append(f'Logs (if created): {detail["log_path"]}')
        rows.extend(['', f'Log directory: {logs}',
                     'Inspect job output and progress state; arbitrary exception text is omitted.'])
        send_message(cfg, f'Icechunker: {label} failed', '\n'.join(rows))
    except Exception:
        # SMTP errors may contain credentials, server responses or recipient addresses.
        print('Icechunker: failure notification could not be delivered; check SMTP configuration/delivery.',
              file=sys.stderr, flush=True)
