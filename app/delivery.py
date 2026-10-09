"""Explicit outbound client jobs. No email is sent merely by marking a quote sent."""
import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from .db import audit,connect,now
from .mfa import encrypt,decrypt

class DocumentEmail(BaseModel):
    copy_id:str=Field(min_length=32,max_length=32)

def queue(db,settings,kind,cid,recipient,payload,copy_id=None,dedupe=None):
    if not settings.email_ready:raise HTTPException(409,'Configure company email and SMTP before queuing client emails')
    identifier=uuid.uuid4().hex
    try:encrypted=encrypt(settings,json.dumps(payload)) if kind=='invite' else json.dumps(payload)
    except ValueError:raise HTTPException(409,'Configure DATA_ENCRYPTION_KEY before emailing invitations')
    db.execute('INSERT OR IGNORE INTO delivery_jobs(id,dedupe_key,kind,client_id,copy_id,recipient,payload,created_at) VALUES(?,?,?,?,?,?,?,?)',(identifier,dedupe or identifier,kind,cid,copy_id,recipient,encrypted,now()))
    return identifier

def queue_reminders(settings):
    today=datetime.now(ZoneInfo(settings.business_timezone)).date().isoformat();count=0
    with connect(settings.db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute("SELECT i.*,c.email FROM invoices i JOIN clients c ON c.id=i.client_id WHERE c.status='active' AND c.reminder_enabled=1 AND i.status='issued' AND i.due_date<? AND i.amount_minor>COALESCE((SELECT sum(amount_minor) FROM payments WHERE invoice_id=i.id),0)",(today,)).fetchall()
        for item in rows:
            # Remind only about a document already explicitly shared with the client.
            shared=db.execute("SELECT c.id FROM document_copies c JOIN portal_documents p ON p.copy_id=c.id WHERE c.kind='invoices' AND c.record_id=? AND c.revoked_at IS NULL ORDER BY c.created_at DESC LIMIT 1",(item['id'],)).fetchone()
            if not shared:continue
            key='overdue:'+item['id']+':'+today
            if db.execute('SELECT 1 FROM delivery_jobs WHERE dedupe_key=?',(key,)).fetchone():continue
            queue(db,settings,'reminder',item['client_id'],item['email'],{'invoice_id':item['id']},shared['id'],key);count+=1
    return count

def drain_jobs(settings,sender=None):
    if not settings.email_ready:return 0
    if sender is None:
        from .mail import send_content
        sender=send_content
    sent=0
    for _ in range(10):
        stamp=int(time.time())
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE delivery_jobs SET state=CASE WHEN attempts>=5 THEN 'failed' ELSE 'pending' END WHERE state='sending' AND lease_at<?",(stamp-900,))
            job=db.execute("SELECT * FROM delivery_jobs WHERE state='pending' AND attempts<5 AND next_attempt<=? ORDER BY created_at,id LIMIT 1",(stamp,)).fetchone()
            if not job:break
            db.execute("UPDATE delivery_jobs SET state='sending',attempts=attempts+1,lease_at=? WHERE id=?",(stamp,job['id']))
        try:
            payload=json.loads(decrypt(settings,job['payload']) if job['kind']=='invite' else job['payload'])
            cancel=False
            with connect(settings.db_path) as db:
                client=db.execute('SELECT * FROM clients WHERE id=?',(job['client_id'],)).fetchone()
                cancel=not client or client['status']!='active'
                if cancel:
                    db.execute("UPDATE delivery_jobs SET state='cancelled',payload='',last_error='' WHERE id=?",(job['id'],))
                    continue
                if job['kind']=='invite':
                    from .security import token_hash
                    invite=db.execute('SELECT * FROM portal_invites WHERE token_hash=? AND used_at IS NULL AND expires>?',(token_hash(payload['token']),stamp)).fetchone()
                    cancel=cancel or not invite or invite['email']!=job['recipient']
                    subject=settings.business_name+' - client portal invitation'
                    body='You were invited to the client portal. This one-use link expires after 24 hours and can set or reset your password. Open it only if you recognize the business.\n\n'+settings.origin+'/client#invite='+payload['token']
                else:
                    item=db.execute('SELECT c.* FROM document_copies c JOIN portal_documents p ON p.copy_id=c.id WHERE c.id=? AND p.client_id=?',(job['copy_id'],job['client_id'])).fetchone()
                    cancel=cancel or not item or bool(item['revoked_at']) or client['email']!=job['recipient']
                    if item:
                        source=db.execute(f"SELECT * FROM {item['kind']} WHERE id=?",(item['record_id'],)).fetchone()
                        from .documents import snapshot,checksum
                        from .pricing import terms
                        if source and checksum(terms(snapshot(db,item['kind'],item['record_id'],settings)))!=checksum(terms(json.loads(item['snapshot_json']))):cancel=True
                        cancel=cancel or not source or source['status'] in {'void','draft','declined','expired'}
                        subject=settings.business_name+' - '+('payment reminder' if job['kind']=='reminder' else 'document available')
                        body='Sign in to your client portal to review document '+json.loads(item['snapshot_json'])['reference']+'.\n\n'+settings.origin+'/client\n\nContact the business if you do not recognize this message.'
                    if job['kind']=='reminder':
                        invoice=db.execute('SELECT * FROM invoices WHERE id=?',(payload['invoice_id'],)).fetchone()
                        paid=db.execute('SELECT COALESCE(sum(amount_minor),0) FROM payments WHERE invoice_id=?',(payload['invoice_id'],)).fetchone()[0]
                        today=datetime.now(ZoneInfo(settings.business_timezone)).date().isoformat()
                        cancel=cancel or not client['reminder_enabled'] or not invoice or invoice['status']!='issued' or paid>=invoice['amount_minor'] or not invoice['due_date'] or invoice['due_date']>=today
                        body+='\nThis is a reminder based on the business’s records. If you have paid, contact the business to review the record.'
            if cancel:
                with connect(settings.db_path) as db:db.execute("UPDATE delivery_jobs SET state='cancelled',payload='',last_error='' WHERE id=?",(job['id'],))
                continue
            sender(settings,job['recipient'],subject,body)
        except Exception:
            with connect(settings.db_path) as db:
                count=job['attempts']+1
                db.execute("UPDATE delivery_jobs SET state=?,next_attempt=?,last_error='Delivery failed; check private email configuration' WHERE id=?",('failed' if count>=5 else 'pending',stamp+min(3600,60*2**count),job['id']))
        else:
            with connect(settings.db_path) as db:
                db.execute("UPDATE delivery_jobs SET state='sent',payload='',last_error='' WHERE id=?",(job['id'],))
                audit(db,None,'client_email_sent',job['id'])
            sent+=1
    return sent

def router(settings,staff):
    r=APIRouter(prefix='/api/admin/delivery',dependencies=[Depends(staff)])
    @r.post('/documents',status_code=201)
    def document(data:DocumentEmail,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            item=db.execute('SELECT c.*,p.client_id,cl.email FROM document_copies c JOIN portal_documents p ON p.copy_id=c.id JOIN clients cl ON cl.id=p.client_id WHERE c.id=? AND c.revoked_at IS NULL AND cl.status=\'active\'',(data.copy_id,)).fetchone()
            if not item:raise HTTPException(409,'Share a current document with an active client in the portal first')
            from .documents import snapshot,checksum
            from .pricing import terms
            original=json.loads(item['snapshot_json'])
            current=snapshot(db,item['kind'],item['record_id'],settings)
            if checksum(terms(original))!=checksum(terms(current)) or current['status'] in {'draft','void','declined','expired'}:raise HTTPException(409,'Issue and share a current copy before sending')
            if not db.execute('SELECT 1 FROM portal_accounts WHERE client_id=? AND email=? AND enabled=1',(item['client_id'],item['email'])).fetchone():raise HTTPException(409,'Activate the client contact’s portal account before sending')
            identifier=queue(db,settings,'document',item['client_id'],item['email'],{},data.copy_id)
            audit(db,user['staff_id'],'queue_document_email',identifier)
        return {'id':identifier,'message':'Email queued. Delivery is not yet confirmed.'}
    @r.get('/jobs')
    def jobs():
        with connect(settings.db_path) as db:return {'items':[dict(x) for x in db.execute('SELECT id,kind,state,attempts,last_error,created_at FROM delivery_jobs ORDER BY created_at DESC LIMIT 100')]}
    return r
