import argparse
import getpass
import os
import sqlite3
from pathlib import Path
from pydantic import EmailStr, TypeAdapter
from .config import load_settings
from .db import connect, initialize
from .mail import drain
from .security import hash_password

def main():
    parser = argparse.ArgumentParser(description="VICAM backend administration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    create = sub.add_parser("create-admin")
    create.add_argument("--email", required=True)
    create.add_argument("--role",choices=["admin","finance","support"],default="admin")
    create.add_argument("--can-issue-documents",action="store_true")
    reset = sub.add_parser("reset-password")
    reset.add_argument("--email", required=True)
    disable = sub.add_parser("disable-admin")
    disable.add_argument("--email", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("destination")
    sub.add_parser("send-notifications")
    permission=sub.add_parser("set-document-permission")
    permission.add_argument("--email",required=True)
    flags=permission.add_mutually_exclusive_group(required=True)
    flags.add_argument("--allow",action="store_true")
    flags.add_argument("--deny",action="store_true")
    test=sub.add_parser("create-test-signing-certificate")
    test.add_argument("destination")
    role=sub.add_parser('set-role');role.add_argument('--email',required=True);role.add_argument('--role',choices=['admin','finance','support'],required=True)
    sub.add_parser('generate-encryption-key')
    enroll=sub.add_parser('prepare-mfa');enroll.add_argument('--email',required=True);enroll.add_argument('--destination',required=True)
    enable=sub.add_parser('enable-mfa');enable.add_argument('--email',required=True)
    off=sub.add_parser('disable-mfa');off.add_argument('--email',required=True)
    sub.add_parser('backup-auto')
    verify=sub.add_parser('verify-backup');verify.add_argument('path')
    restore=sub.add_parser('restore-backup');restore.add_argument('path');restore.add_argument('--destination',required=True)
    reminders=sub.add_parser('queue-reminders');reminders.add_argument('--confirm',action='store_true')
    purge=sub.add_parser('purge-history');purge.add_argument('--before',required=True);purge.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    settings = load_settings()
    initialize(settings.db_path)
    if args.command=='generate-encryption-key':
        from cryptography.fernet import Fernet
        print('DATA_ENCRYPTION_KEY='+Fernet.generate_key().decode())
    elif args.command=='set-role':
        with connect(settings.db_path) as db:
            user=db.execute('SELECT id FROM staff WHERE email=?',(args.email.lower(),)).fetchone()
            if not user:parser.error('Account not found')
            db.execute('UPDATE staff SET role=? WHERE id=?',(args.role,user['id']))
            db.execute('DELETE FROM sessions WHERE staff_id=?',(user['id'],))
        print('Role updated. Sign in again.')
    elif args.command in {'prepare-mfa','enable-mfa','disable-mfa'}:
        from .mfa import encrypt,decrypt,matching_counter
        import secrets,base64,json
        from urllib.parse import quote
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            user=db.execute('SELECT * FROM staff WHERE email=?',(args.email.lower(),)).fetchone()
            if not user:parser.error('Account not found')
            if args.command=='prepare-mfa':
                target=Path(args.destination).resolve()
                if target.is_relative_to((settings.db_path.parent.parent/'static').resolve()) or target.is_relative_to((Path(__file__).resolve().parent.parent/'static').resolve()):parser.error('MFA setup must be private, outside static')
                secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
                try:encrypted=encrypt(settings,secret)
                except ValueError:parser.error('Configure DATA_ENCRYPTION_KEY first')
                uri='otpauth://totp/'+quote(settings.business_name+':'+args.email,safe='')+'?secret='+secret+'&issuer='+quote(settings.business_name,safe='')+'&algorithm=SHA1&digits=6&period=30'
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as file:json.dump({'account':args.email,'secret':secret,'authenticator_uri':uri},file)
                db.execute('UPDATE staff SET mfa_pending=? WHERE id=?',(encrypted,user['id']))
                print('Private MFA setup file created. Add its secret to your authenticator, enable MFA, then securely remove this file.')
            elif args.command=='enable-mfa':
                if not user['mfa_pending']:parser.error('Prepare MFA first')
                counter=matching_counter(decrypt(settings,user['mfa_pending']),getpass.getpass('Authenticator code: '))
                if counter is None:parser.error('Code not accepted')
                db.execute("UPDATE staff SET mfa_secret=mfa_pending,mfa_pending='',mfa_last_counter=? WHERE id=?",(counter,user['id']))
                db.execute('DELETE FROM sessions WHERE staff_id=?',(user['id'],))
                print('MFA enabled. Sign in with password and a fresh authenticator code.')
            else:
                db.execute("UPDATE staff SET mfa_secret='',mfa_pending='',mfa_last_counter=-1 WHERE id=?",(user['id'],))
                db.execute('DELETE FROM sessions WHERE staff_id=?',(user['id'],))
                print('MFA disabled by local administrator. Review account security and enroll again.')
    elif args.command in {'backup-auto','verify-backup','restore-backup'}:
        from .operations import make_backup,verify_backup
        if args.command=='backup-auto':
            make_backup(settings);print('Verified automatic backup created.')
        else:
            verify_backup(Path(args.path))
            if args.command=='restore-backup':
                target=Path(args.destination).resolve()
                if target.exists() or target==settings.db_path.resolve():parser.error('Restore only to a new isolated database path')
                from .config import ROOT
                if target.is_relative_to((ROOT/'static').resolve()):parser.error('Restore must be private, outside static')
                target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
                with sqlite3.connect(Path(args.path).resolve().as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(target) as dest:source.backup(dest)
                print('Restored to a new database. Keep the production database unchanged during testing.')
            else:print('Backup fingerprint and database integrity verified.')
    elif args.command=='queue-reminders':
        if not args.confirm:parser.error('Use --confirm only after clients have agreed to reminders')
        from .delivery import queue_reminders
        print('Client reminders queued:',queue_reminders(settings))
    elif args.command=='purge-history':
        from datetime import date
        cutoff=date.fromisoformat(args.before)
        if cutoff>=date.today():parser.error('Use a past cutoff date agreed in your retention policy')
        with connect(settings.db_path) as db:
            count=db.execute('SELECT count(*) FROM record_history WHERE created_at<?',(cutoff.isoformat(),)).fetchone()[0]
            if args.apply:db.execute('DELETE FROM record_history WHERE created_at<?',(cutoff.isoformat(),))
        print(('Purged' if args.apply else 'Dry run: would purge'),count,'history entries. Original documents and backups are unchanged.')
    elif args.command == "set-document-permission":
        email=str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
        with connect(settings.db_path) as db:
            result=db.execute("UPDATE staff SET can_issue_docs=? WHERE email=?",(int(args.allow),email))
            if not result.rowcount:parser.error("Account not found")
            db.execute("DELETE FROM sessions WHERE staff_id IN (SELECT id FROM staff WHERE email=?)",(email,))
        print("Document issuing permission updated. Sign in again.")
    elif args.command == "create-test-signing-certificate":
        if settings.production:parser.error("Test certificates cannot be generated in production")
        password=getpass.getpass("Test certificate password (12+ characters): ")
        if len(password)<12 or password!=getpass.getpass("Confirm password: "):parser.error("Use matching passwords of at least 12 characters")
        from .pdf_signing import create_test_certificate
        try:create_test_certificate(Path(args.destination),password)
        except FileExistsError:parser.error("Choose a new private test certificate file")
        print("Local test certificate created. It is not a trusted company identity.")
    elif args.command in {"create-admin", "reset-password", "disable-admin"}:
        email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
        if args.command != "disable-admin":
            password = getpass.getpass("Password (at least 12 characters): ")
            if len(password) < 12 or len(password) > 512 or password != getpass.getpass("Confirm password: "):
                parser.error("Use matching passwords of 12–512 characters")
        with connect(settings.db_path) as db:
            user = db.execute("SELECT id FROM staff WHERE email=?", (email,)).fetchone()
            if args.command == "create-admin":
                if user:
                    parser.error("Account already exists; use reset-password")
                db.execute("INSERT INTO staff(email,password_hash,can_issue_docs,role) VALUES(?,?,?,?)", (email,hash_password(password),int(args.can_issue_documents),args.role))
            else:
                if not user:
                    parser.error("Account not found")
                if args.command == "reset-password":
                    db.execute("UPDATE staff SET password_hash=? WHERE id=?", (hash_password(password),user[0]))
                else:
                    db.execute("UPDATE staff SET enabled=0 WHERE id=?", (user[0],))
                db.execute("DELETE FROM sessions WHERE staff_id=?", (user[0],))
        print("Account updated.")
    elif args.command == "backup":
        target = Path(args.destination).resolve()
        if target == settings.db_path.resolve() or target.exists():
            parser.error("Choose a new backup file path")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(settings.db_path) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        print("Backup created. Protect it as client data.")
    elif args.command == "send-notifications":
        if not settings.email_ready:
            parser.error("Configure SMTP_HOST, MAIL_FROM and COMPANY_EMAIL first")
        from .delivery import drain_jobs
        print("Notifications sent:", drain(settings)+drain_jobs(settings))
    else:
        print("Database initialized.")

if __name__ == "__main__":
    main()
