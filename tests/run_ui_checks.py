"""Optional integration check: npm install, then python tests/run_ui_checks.py."""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.db import initialize,connect
from app.security import hash_password

def main():
    # Local-only fixture account and records live in a disposable directory.
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(temporary)/'smoke.sqlite3'
        initialize(path)
        with connect(path) as db:
            db.execute('INSERT INTO staff(email,password_hash,can_issue_docs) VALUES(?,?,1)',('staff@example.com',hash_password('local-smoke-password')))
        with connect(path) as db:
            for role in ('finance','support'):
                db.execute('INSERT INTO staff(email,password_hash,role,can_issue_docs) VALUES(?,?,?,?)',(role+'@example.com',hash_password('local-smoke-password'),role,int(role=='finance')))
        from app.pdf_signing import create_test_certificate
        certificate=Path(temporary)/'local-test.p12'
        create_test_certificate(certificate,'local-test-secret-password')
        origin='http://127.0.0.1:8767'
        env=dict(os.environ,DATABASE_PATH=str(path),PUBLIC_ORIGIN=origin,SMOKE_ORIGIN=origin,APP_ENV='development',SECURE_COOKIES='false',SMTP_HOST='',MAIL_FROM='',COMPANY_EMAIL='',SMTP_USER='',SMTP_PASSWORD='',PDF_SIGNING_MODE='test',PDF_SIGNING_PFX=str(certificate),PDF_SIGNING_PASSWORD='local-test-secret-password')
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port','8767','--no-proxy-headers','--no-access-log'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(40):
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read().decode())
                try:
                    opener.open(origin+'/api/health',timeout=1)
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Test server did not start. Check that port 8767 is free.')
            # A short readiness check avoids connecting to an unrelated process.
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode())
            for script in ('ui_workflows.cjs','experience_ui.cjs','role_ui.cjs','assistant_ui.cjs','education_motion_ui.cjs','service_records_ui.cjs'):
                subprocess.run(['node',str(ROOT/'tests'/script)],cwd=ROOT,env=env,timeout=60,check=True)
        finally:
            process.terminate()
            process.communicate(timeout=10)

if __name__=='__main__':
    main()
