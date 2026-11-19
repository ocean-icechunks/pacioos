"""Best-effort SMTP alerts containing job summaries and explicitly safe recovery guidance."""
from email.message import EmailMessage
import os
import smtplib
import ssl
import sys


def send_message(subject, body):
    recipients = [value.strip() for value in os.environ.get('PACIOOS_ALERT_EMAIL_TO', '').split(',')]
    sender = os.environ.get('PACIOOS_ALERT_EMAIL_FROM', '')
    if any(not value or '@' not in value or '\r' in value or '\n' in value
           for value in [sender, *recipients]):
        raise ValueError('Configure valid alert sender and recipients')
    host = os.environ.get('PACIOOS_SMTP_HOST')
    if not host:
        raise ValueError('PACIOOS_SMTP_HOST is required')
    security = os.environ.get('PACIOOS_SMTP_SECURITY', 'starttls').lower()
    if security not in ('starttls', 'ssl'):
        raise ValueError('SMTP security must be starttls or ssl')
    port = int(os.environ.get('PACIOOS_SMTP_PORT', '465' if security == 'ssl' else '587'))
    username = os.environ.get('PACIOOS_SMTP_USERNAME')
    password = os.environ.get('PACIOOS_SMTP_PASSWORD')
    if bool(username) != bool(password):
        raise ValueError('Configure both SMTP username and password, or neither')

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


def notify_failures(action, scope, failures, logs, details=None):
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
        send_message(f'Icechunker: {label} failed', '\n'.join(rows))
    except Exception:
        # SMTP errors may contain credentials, server responses or recipient addresses.
        print('Icechunker: failure notification could not be delivered; check SMTP configuration/delivery.',
              file=sys.stderr, flush=True)
