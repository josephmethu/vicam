import asyncio
import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from .db import connect

log = logging.getLogger("vicam.mail")

def send(settings, reference, service):
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = settings.company_email
    message["Subject"] = f"VICAM enquiry {reference}"
    message.set_content(f"A new {service} enquiry has been saved.\nReference: {reference}\n\nSign in to view the brief: {settings.origin}/admin\n\nClient details are kept in the dashboard rather than this notification.")
    deliver(settings,message)

def send_content(settings,recipient,subject,body):
    message=EmailMessage();message["From"]=settings.mail_from;message["To"]=recipient;message["Subject"]=subject;message.set_content(body)
    deliver(settings,message)

def deliver(settings,message):
    context = ssl.create_default_context()
    if settings.smtp_mode == "ssl":
        client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
    else:
        client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with client:
        if settings.smtp_mode == "starttls":
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)

def drain(settings, sender=send):
    if not settings.email_ready:
        return 0
    completed = 0
    for _ in range(10):
        stamp = int(time.time())
        with connect(settings.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE outbox SET state=CASE WHEN attempts>=5 THEN 'failed' ELSE 'pending' END,last_error='Delivery interrupted; check notification status' WHERE state='sending' AND lease_at<?", (stamp-900,))
            row = db.execute("SELECT o.enquiry_id,e.reference,e.service FROM outbox o JOIN enquiries e ON e.id=o.enquiry_id WHERE o.state='pending' AND o.next_attempt<=? AND o.attempts<5 LIMIT 1", (stamp,)).fetchone()
            if not row:
                break
            db.execute("UPDATE outbox SET state='sending',attempts=attempts+1,lease_at=? WHERE enquiry_id=?", (stamp, row["enquiry_id"]))
        try:
            sender(settings, row["reference"], row["service"])
        except Exception:
            # Do not persist SMTP exceptions containing addresses, credentials or server details.
            with connect(settings.db_path) as db:
                attempts = db.execute("SELECT attempts FROM outbox WHERE enquiry_id=?", (row["enquiry_id"],)).fetchone()
                if attempts:
                    count = attempts[0]
                    db.execute("UPDATE outbox SET state=?,next_attempt=?,last_error='Delivery failed; check server SMTP configuration' WHERE enquiry_id=?", ("failed" if count >= 5 else "pending", stamp + min(3600, 60 * 2 ** count), row["enquiry_id"]))
            log.warning("An enquiry email notification could not be delivered")
        else:
            with connect(settings.db_path) as db:
                db.execute("UPDATE outbox SET state='sent',last_error='' WHERE enquiry_id=?", (row["enquiry_id"],))
            completed += 1
    return completed

async def worker(settings):
    last_reminder_date=None
    while True:
        try:
            await asyncio.to_thread(drain, settings)
            from .delivery import drain_jobs,queue_reminders
            from datetime import datetime
            from zoneinfo import ZoneInfo
            today=datetime.now(ZoneInfo(settings.business_timezone)).date().isoformat()
            if settings.reminder_emails_enabled and last_reminder_date!=today:
                await asyncio.to_thread(queue_reminders,settings)
                last_reminder_date=today
            await asyncio.to_thread(drain_jobs,settings)
        except Exception:
            log.error("Notification worker error; enquiries remain in the database")
        await asyncio.sleep(30)
