"""Only server-configured admin recipients receive test results."""
from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage

from .database import set_email_status, failed_notification

log = logging.getLogger(__name__)


def send_result(settings, result_id: int, record: dict) -> None:
    if not settings.smtp_host or not settings.smtp_to or not settings.smtp_from:
        set_email_status(settings.db_path, result_id, "disabled")
        return
    message = EmailMessage()
    # Config-only fields could still contain newline; never allow email header injection.
    clean_school = str(record['school']).replace('\r', ' ').replace('\n', ' ')[:80]
    clean_agent = str(record.get('agent_id') or 'Manual browser').replace('\r', ' ').replace('\n', ' ')[:64]
    message['Subject'] = (f"[GMCS Inside Speed Test] {clean_school} | "
                          f"VLAN {record['vlan']} | "
                          f"{'Scheduled ' + clean_agent if record.get('agent_id') else 'Manual'} | "
                          f"{record['download_mbps']:.1f} Mbps down")
    message['From'] = settings.smtp_from
    message['To'] = ', '.join(settings.smtp_to)
    message.set_content(
        'GMCS Internal Speed Test Result\n\n'
        f"Result ID: {result_id}\n"
        f"Test type: {'Scheduled Linux agent' if record.get('agent_id') else 'Manual browser'}\n"
        f"Agent ID: {clean_agent}\n"
        f"School: {clean_school}\n"
        f"VLAN: {record['vlan']}\n"
        f"Network: {record['network_label']}\n"
        f"Observed source IP: {record['client_ip']}\n"
        f"Download: {record['download_mbps']:.2f} Mbps\n"
        f"Upload: {record['upload_mbps']:.2f} Mbps\n"
        f"Latency: {record['latency_ms']:.2f} ms\n"
        f"Jitter: {record['jitter_ms']:.2f} ms\n"
        f"Probe failure rate: {record['packet_loss_pct']:.1f}%\n"
        f"Test bytes: down {record['download_bytes']}, up {record['upload_bytes']}\n\n"
        'Throughput measured to GMCS internal test VM; NOT Internet/ISP speed.\n'
        'School/VLAN derived from observed client IP and private configured mapping.\n'
        'Metrics are reported by the client and should be treated as diagnostic, not cryptographic proof.\n'
    )
    # A small number of retries handle temporary SMTP relay failures.
    for attempt in range(3):
        try:
            context = ssl.create_default_context()
            if settings.smtp_tls_mode == 'ssl':
                connection = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=12, context=context)
            else:
                connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=12)
            with connection as client:
                client.ehlo()
                if settings.smtp_tls_mode == 'starttls':
                    client.starttls(context=context)
                    client.ehlo()
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
            set_email_status(settings.db_path, result_id, 'sent')
            return
        except Exception:
            log.warning('SMTP delivery attempt %d failed for result #%d', attempt + 1, result_id, exc_info=True)
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    failed_notification(settings.db_path, result_id)
