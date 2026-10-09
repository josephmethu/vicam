import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

@dataclass(frozen=True)
class Settings:
    db_path: Path
    origin: str = "http://127.0.0.1:8000"
    production: bool = False
    secure_cookie: bool = False
    session_hours: int = 8
    business_timezone: str = "Africa/Nairobi"
    pdf_signing_mode: str = "disabled"
    pdf_signing_pfx: str = ""
    pdf_signing_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_mode: str = "starttls"
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    company_email: str = ""
    assistant_ai_key: str = ""
    assistant_ai_model: str = ""
    reminder_emails_enabled: bool = False
    data_encryption_key: str = ""
    backup_directory: str = ""
    backup_interval_hours: int = 24
    backup_keep: int = 14
    business_name: str = "VICAM"
    business_registration: str = ""
    verification_public_details: bool = True

    @property
    def email_ready(self):
        return bool(self.smtp_host and self.mail_from and self.company_email)

    def validate(self):
        from pydantic import TypeAdapter, EmailStr
        if bool(self.assistant_ai_key)!=bool(self.assistant_ai_model):raise ValueError("Configure both ASSISTANT_AI_KEY and ASSISTANT_AI_MODEL, or leave both empty")
        if self.reminder_emails_enabled and not self.email_ready:raise ValueError("Automatic reminders require configured SMTP, sender and company email")
        from zoneinfo import ZoneInfo
        if self.data_encryption_key:
            from cryptography.fernet import Fernet
            Fernet(self.data_encryption_key.encode())
        if not 1<=self.backup_interval_hours<=168 or not 3<=self.backup_keep<=365:raise ValueError("Backup interval must be 1-168 hours and backup retention 3-365 copies")
        if self.backup_directory:
            backup=Path(self.backup_directory).resolve()
            if backup==ROOT.resolve() or backup==self.db_path.resolve().parent:raise ValueError("Use a separate private backup directory")
            if backup.is_relative_to((ROOT/"static").resolve()):raise ValueError("Backups cannot be stored under static")
        ZoneInfo(self.business_timezone)
        if not self.business_name.strip() or len(self.business_name)>100 or len(self.business_registration)>100:
            raise ValueError("Business name and registration must be at most 100 characters")
        if self.pdf_signing_mode not in {"disabled","test","certificate"}:
            raise ValueError("PDF_SIGNING_MODE must be disabled, test or certificate")
        if self.production and self.pdf_signing_mode == "test":
            raise ValueError("Local test PDF signing is not allowed in production")
        if self.pdf_signing_mode != "disabled":
            try:
                Path(self.pdf_signing_pfx).resolve().relative_to((ROOT / "static").resolve())
            except ValueError:
                pass
            else:
                raise ValueError("Signing keys must never be stored under static")
            from .pdf_signing import load_signer
            try:
                load_signer(self)
            except Exception:
                raise ValueError("Signing configuration is invalid; check certificate, password, validity and key usage") from None
        url = urlsplit(self.origin)
        if url.scheme not in {"http", "https"} or not url.netloc or url.path not in {"", "/"} or url.query or url.fragment or url.username:
            raise ValueError("PUBLIC_ORIGIN must be an http(s) origin without a path")
        if self.production and (url.scheme != "https" or not self.secure_cookie):
            raise ValueError("Production requires HTTPS PUBLIC_ORIGIN and SECURE_COOKIES=true")
        if self.smtp_mode not in {"starttls", "ssl"}:
            raise ValueError("SMTP_MODE must be starttls or ssl")
        if not 1 <= self.session_hours <= 24:
            raise ValueError("SESSION_HOURS must be between 1 and 24")
        for value in (self.mail_from, self.company_email):
            if value:
                TypeAdapter(EmailStr).validate_python(value)
        return self

def load_settings():
    load_dotenv(ROOT / ".env")
    return Settings(
        assistant_ai_key=os.getenv("ASSISTANT_AI_KEY", ""),
        assistant_ai_model=os.getenv("ASSISTANT_AI_MODEL", ""),
        reminder_emails_enabled=os.getenv("REMINDER_EMAILS_ENABLED", "false").lower()=="true",
        data_encryption_key=os.getenv("DATA_ENCRYPTION_KEY", ""),
        backup_directory=os.getenv("BACKUP_DIRECTORY", ""),
        backup_interval_hours=int(os.getenv("BACKUP_INTERVAL_HOURS", "24")),
        backup_keep=int(os.getenv("BACKUP_KEEP", "14")),
        business_name=os.getenv("BUSINESS_NAME", "VICAM"),
        business_registration=os.getenv("BUSINESS_REGISTRATION", ""),
        verification_public_details=os.getenv("VERIFICATION_PUBLIC_DETAILS", "true").lower()=="true",
        db_path=Path(os.getenv("DATABASE_PATH", str(ROOT / "data/vicam.sqlite3"))),
        origin=os.getenv("PUBLIC_ORIGIN", "http://127.0.0.1:8000").rstrip("/"),
        production=os.getenv("APP_ENV", "development") == "production",
        secure_cookie=os.getenv("SECURE_COOKIES", "false").lower() == "true",
        session_hours=int(os.getenv("SESSION_HOURS", "8")),
        business_timezone=os.getenv("BUSINESS_TIMEZONE", "Africa/Nairobi"),
        pdf_signing_mode=os.getenv("PDF_SIGNING_MODE","disabled"),
        pdf_signing_pfx=os.getenv("PDF_SIGNING_PFX",""),
        pdf_signing_password=os.getenv("PDF_SIGNING_PASSWORD",""),
        smtp_host=os.getenv("SMTP_HOST", ""), smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_mode=os.getenv("SMTP_MODE", "starttls"), smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""), mail_from=os.getenv("MAIL_FROM", ""),
        company_email=os.getenv("COMPANY_EMAIL", ""),
    ).validate()
