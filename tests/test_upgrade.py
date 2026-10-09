import json,time,sqlite3
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from test_backend import client,signin,PASSWORD
from test_crm import create,profile,issued,payment,BASE
from test_documents import copy,verify
from app.db import connect,initialize
from app.main import create_app
from app.pricing import calculate,LineItem
from app.mfa import encrypt,decrypt,code
from app.operations import make_backup,verify_backup
from app.delivery import drain_jobs,queue_reminders


def priced(cid,**kwargs):
    return dict(client_id=cid,title='Installation',line_items=[{'description':'Camera installation','quantity':'2','unit_amount_minor':10000}],discount_percent='10',vat_percent='16',**kwargs)

def test_calculated_money_snapshot_pdf_and_paid_invoice_lock(client):
    h=signin(client);c=profile(client,h)
    q=create(client,'quotes',priced(c['id'],status='sent'),h)
    assert q['amount_minor']==20880
    assert q['pricing']['subtotal_minor']==20000 and q['pricing']['discount_minor']==2000 and q['pricing']['vat_minor']==2880
    original=copy(client,'quotes',q,h)
    assert original['snapshot']['pricing']['total_minor']==20880
    pdf=client.get(original['download_url']).content
    import io
    from pypdf import PdfReader
    text=''.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    assert 'Camera installation' in text and 'VAT (16%)' in text and 'Discount (10%)' in text
    i=create(client,'invoices',priced(c['id'],status='issued'),h)
    create(client,'payments',payment(i,1000),h)
    changed=priced(c['id'],status='issued');changed['line_items'][0]['description']='Different scope'
    assert client.put(BASE+'invoices/'+i['id'],json=changed,headers=h).status_code==409
    assert client.get('/api/admin/operations/history/quotes/'+q['id']).json()['items'][0]['after']['amount_minor']==20880


def test_rounding_preview_and_reject_invalid_pricing(client):
    h=signin(client);c=profile(client,h)
    p=priced(c['id']);p['amount_minor']=1
    assert client.post(BASE+'quotes',json=p,headers=h).status_code==422
    for field,value in [('quantity',True),('quantity','NaN'),('quantity','0'),('quantity','1.00001'),('unit_amount_minor',1.5)]:
        p=priced(c['id']);p['line_items'][0][field]=value
        assert client.post(BASE+'quotes',json=p,headers=h).status_code==422
    p=priced(c['id']);p['vat_percent']='16.001'
    assert client.post(BASE+'quotes',json=p,headers=h).status_code==422
    p=priced(c['id']);p['discount_percent']='100'
    assert client.post(BASE+'quotes',json=p,headers=h).status_code==422
    result=calculate([LineItem(description='Fraction',quantity=Decimal('1.5'),unit_amount_minor=101)],Decimal('10'),Decimal('16'))
    assert (result['subtotal_minor'],result['discount_minor'],result['vat_minor'],result['total_minor'])==(152,15,22,159)
    res=client.post(BASE+'calculate',json=priced(c['id']),headers=h)
    assert res.status_code==200 and res.json()['total_minor']==20880


def test_role_enforcement_not_just_hidden_buttons(client):
    h=signin(client);c=profile(client,h);q=create(client,'quotes',priced(c['id']),h)
    with connect(client.settings.db_path) as db:db.execute("UPDATE staff SET role='support'")
    assert client.get(BASE+'quotes').status_code==403
    assert client.get('/api/admin/documents/quotes/'+q['id']+'/copies').status_code==403
    assert client.get('/api/admin/operations/status').status_code==403
    assert client.delete(BASE+'clients/'+c['id'],headers=h).status_code==403
    assert client.get(BASE+'clients').status_code==200
    assert client.get('/api/admin/experience/follow-ups').status_code==200
    with connect(client.settings.db_path) as db:db.execute("UPDATE staff SET role='finance'")
    assert client.get(BASE+'quotes').status_code==200
    assert client.put(BASE+'clients/'+c['id'],json={'name':'Changed','email':'client@example.com'},headers=h).status_code==403
    assert client.get('/api/admin/enquiries').status_code==403
    assert client.get('/api/admin/operations/status').status_code==403
    assert client.get('/api/admin/delivery/jobs').status_code==403


def test_mfa_requires_code_encrypted_and_prevents_replay(client):
    settings=replace(client.settings,data_encryption_key=Fernet.generate_key().decode())
    secret='JBSWY3DPEHPK3PXP'
    with connect(settings.db_path) as db:db.execute('UPDATE staff SET mfa_secret=?',(encrypt(settings,secret),))
    with TestClient(create_app(settings,enable_mail_worker=False)) as secured:
        login={'email':'staff@example.com','password':PASSWORD}
        assert secured.post('/api/auth/login',json=login).status_code==401
        counter=int(time.time())//30;login['otp']=code(secret,counter)
        assert secured.post('/api/auth/login',json=login).status_code==200
        assert secured.post('/api/auth/login',json=login).status_code==401
        with connect(settings.db_path) as db:
            u=db.execute('SELECT * FROM staff').fetchone()
            assert secret not in u['mfa_secret'] and decrypt(settings,u['mfa_secret'])==secret and u['mfa_last_counter']==counter


def test_verified_backup_restore_and_tamper_detection(client,tmp_path):
    settings=replace(client.settings,backup_directory=str(tmp_path/'protected-backups'))
    h=signin(client);c=profile(client,h)
    path=make_backup(settings);assert verify_backup(path)['schema']==8
    with sqlite3.connect(path) as db:assert db.execute('SELECT name FROM clients WHERE id=?',(c['id'],)).fetchone()[0]==c['name']
    with path.open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError):verify_backup(path)
    with pytest.raises(ValueError):replace(settings,backup_directory=str(Path(__file__).parent.parent/'static'/'backups')).validate()


def setup_delivery(client):
    settings=replace(client.settings,smtp_host='mail.example.com',mail_from='sender@example.com',company_email='office@example.com',data_encryption_key=Fernet.generate_key().decode())
    return settings


def test_invite_outbox_encryption_delivery_and_retry(client):
    settings=setup_delivery(client)
    with TestClient(create_app(settings,enable_mail_worker=False)) as mail:
        h=signin(mail);c=profile(mail,h)
        response=mail.post('/api/admin/experience/clients/'+c['id']+'/invite',json={'email':'client@example.com','send_email':True},headers=h)
        assert response.status_code==201 and response.json()['email_queued']
        token=response.json()['activation_url'].split('invite=')[1]
        with connect(settings.db_path) as db:
            payload=db.execute('SELECT payload FROM delivery_jobs').fetchone()[0];assert token not in payload
        sent=[]
        assert drain_jobs(settings,lambda *args:sent.append(args))==1
        assert token in sent[0][3] and sent[0][1]=='client@example.com'
        with connect(settings.db_path) as db:assert db.execute('SELECT payload FROM delivery_jobs').fetchone()[0]==''
        assert drain_jobs(settings,lambda *args:sent.append(args))==0


def test_opt_in_reminders_dedupe_and_paid_before_send(client):
    settings=setup_delivery(client)
    with TestClient(create_app(settings,enable_mail_worker=False)) as mail:
        h=signin(mail);c=profile(mail,h);i=issued(mail,h,c['id']);original=copy(mail,'invoices',i,h)
        # Existing invite/share routes supply the intended authenticated audience.
        invite=mail.post('/api/admin/experience/clients/'+c['id']+'/invite',json={'email':'client@example.com'},headers=h).json()
        activation=mail.post('/api/client/activate',json={'token':invite['activation_url'].split('invite=')[1],'password':'client-long-password'})
        assert activation.status_code==200
        assert mail.post('/api/admin/experience/clients/'+c['id']+'/documents',json={'copy_id':original['id']},headers=h).status_code==201
        with connect(settings.db_path) as db:db.execute("UPDATE invoices SET due_date='2020-01-01' WHERE id=?",(i['id'],))
        # Issue/share the current terms after changing the due date.
        original=copy(mail,'invoices',i,h)
        mail.post('/api/admin/experience/clients/'+c['id']+'/documents',json={'copy_id':original['id']},headers=h)
        assert queue_reminders(settings)==0
        with connect(settings.db_path) as db:db.execute('UPDATE clients SET reminder_enabled=1 WHERE id=?',(c['id'],))
        assert queue_reminders(settings)==1 and queue_reminders(settings)==0
        create(mail,'payments',payment(i,10000),h)
        sent=[];assert drain_jobs(settings,lambda *args:sent.append(args))==0 and sent==[]
        with connect(settings.db_path) as db:assert db.execute('SELECT state FROM delivery_jobs').fetchone()[0]=='cancelled'


def test_document_notification_requires_shared_portal_account_and_export_privacy(client):
    h=signin(client);c=profile(client,h);q=create(client,'quotes',priced(c['id'],status='sent'),h);original=copy(client,'quotes',q,h)
    assert client.post('/api/admin/delivery/documents',json={'copy_id':original['id']},headers=h).status_code==409
    exported=client.get('/api/admin/operations/clients/'+c['id']+'/export')
    assert exported.status_code==200 and 'attachment' in exported.headers['content-disposition']
    assert 'password_hash' not in exported.text and original['verification_url'].split('#')[1] not in exported.text
    assert client.get('/api/admin/operations/status').json()['database_ok'] is True


def test_daily_reminder_worker_runs_once_per_business_day(client,monkeypatch):
    import asyncio
    from app.mail import worker
    settings=replace(setup_delivery(client),reminder_emails_enabled=True)
    calls=[];iterations=[]
    monkeypatch.setattr('app.mail.drain',lambda s:0)
    monkeypatch.setattr('app.delivery.queue_reminders',lambda s:calls.append('queue') or 0)
    monkeypatch.setattr('app.delivery.drain_jobs',lambda s:calls.append('drain') or 0)
    async def stop_after_two(delay):
        iterations.append(delay)
        if len(iterations)==2:raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio,'sleep',stop_after_two)
    with pytest.raises(asyncio.CancelledError):asyncio.run(worker(settings))
    assert calls.count('queue')==1 and calls.count('drain')==2
    with pytest.raises(ValueError):replace(client.settings,reminder_emails_enabled=True).validate()


def test_failed_email_retry_is_bounded_and_error_is_sanitized(client):
    settings=setup_delivery(client)
    with TestClient(create_app(settings,enable_mail_worker=False)) as mail:
        h=signin(mail);c=profile(mail,h)
        assert mail.post('/api/admin/experience/clients/'+c['id']+'/invite',json={'email':'client@example.com','send_email':True},headers=h).status_code==201
        def fails(*args):raise RuntimeError('PRIVATE SMTP PASSWORD')
        assert drain_jobs(settings,fails)==0
        with connect(settings.db_path) as db:
            job=db.execute('SELECT * FROM delivery_jobs').fetchone()
            assert job['state']=='pending' and job['attempts']==1 and 'PRIVATE' not in job['last_error']
            db.execute('UPDATE delivery_jobs SET next_attempt=0,attempts=4')
        assert drain_jobs(settings,fails)==0
        with connect(settings.db_path) as db:assert db.execute('SELECT state FROM delivery_jobs').fetchone()[0]=='failed'
        assert drain_jobs(settings,fails)==0


def test_restore_command_refuses_live_path_and_restores_new_path(client,tmp_path):
    import subprocess,sys,os
    settings=replace(client.settings,backup_directory=str(tmp_path/'backups'))
    h=signin(client);c=profile(client,h);backup=make_backup(settings)
    env=dict(os.environ,DATABASE_PATH=str(settings.db_path),PUBLIC_ORIGIN=settings.origin,APP_ENV='development',PDF_SIGNING_MODE='disabled',DATA_ENCRYPTION_KEY='',REMINDER_EMAILS_ENABLED='false',BACKUP_DIRECTORY='')
    root=Path(__file__).resolve().parent.parent
    args=[sys.executable,'-m','app.manage','restore-backup',str(backup),'--destination']
    refused=subprocess.run(args+[str(settings.db_path)],cwd=root,env=env,capture_output=True,text=True)
    assert refused.returncode!=0
    target=tmp_path/'restore'/'new.sqlite3'
    restored=subprocess.run(args+[str(target)],cwd=root,env=env,capture_output=True,text=True)
    assert restored.returncode==0,restored.stderr
    with sqlite3.connect(target) as db:assert db.execute('SELECT email FROM clients WHERE id=?',(c['id'],)).fetchone()[0]==c['email']


def test_totp_sha1_matches_standard_hotp_vectors():
    import base64
    secret=base64.b32encode(b'12345678901234567890').decode()
    assert code(secret,0)=='755224' and code(secret,1)=='287082'
