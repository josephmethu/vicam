"""Client-facing collaboration. Explicit publication; separate client sessions."""
import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from .config import ROOT
from .db import audit, connect, now
from .security import DUMMY_HASH, check_password, hash_password, rate_limit, token_hash
from .documents import canonical, checksum, snapshot
from .pricing import terms
from fastapi.responses import FileResponse

SCHEMA = '''
CREATE TABLE IF NOT EXISTS portal_accounts(id TEXT PRIMARY KEY,client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS portal_invites(token_hash TEXT PRIMARY KEY,client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,email TEXT NOT NULL,expires INTEGER NOT NULL,used_at TEXT);
CREATE TABLE IF NOT EXISTS portal_sessions(token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES portal_accounts(id) ON DELETE CASCADE,csrf TEXT NOT NULL,expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS project_progress(project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,stage TEXT NOT NULL,summary TEXT NOT NULL,next_milestone TEXT NOT NULL,waiting_on TEXT NOT NULL,target_date TEXT,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS portal_documents(copy_id TEXT PRIMARY KEY REFERENCES document_copies(id) ON DELETE CASCADE,client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,shared_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quote_decisions(id TEXT PRIMARY KEY,copy_id TEXT NOT NULL REFERENCES document_copies(id),client_id TEXT NOT NULL REFERENCES clients(id),account_id TEXT NOT NULL REFERENCES portal_accounts(id),action TEXT NOT NULL,message TEXT NOT NULL,checksum TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS accepted_quote_copy ON quote_decisions(copy_id) WHERE action='accept';
CREATE TABLE IF NOT EXISTS ticket_messages(id TEXT PRIMARY KEY,ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,author TEXT NOT NULL,text TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS client_files(id TEXT PRIMARY KEY,client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,project_id TEXT REFERENCES projects(id) ON DELETE RESTRICT,name TEXT NOT NULL,mime TEXT NOT NULL,content BLOB NOT NULL,sha256 TEXT NOT NULL,uploaded_by TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS files_client ON client_files(client_id);
CREATE TABLE IF NOT EXISTS case_studies(id TEXT PRIMARY KEY,title TEXT NOT NULL,service TEXT NOT NULL,problem TEXT NOT NULL,solution TEXT NOT NULL,result TEXT NOT NULL,published INTEGER NOT NULL DEFAULT 0,permission_confirmed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
'''
COOKIE = 'vicam_client_session'
MAX_FILE = 2 * 1024 * 1024

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Invite(Model):
    email: EmailStr
    send_email: bool = False

class Activation(Model):
    token: str = Field(min_length=43,max_length=43)
    password: str = Field(min_length=12,max_length=512)

class PortalLogin(Model):
    email: EmailStr
    password: str = Field(min_length=1,max_length=512)

class Progress(Model):
    stage: Literal['discovery','planning','implementation','testing','handover','ongoing_support']
    summary: str = Field(min_length=2,max_length=2000)
    next_milestone: str = Field(default='',max_length=500)
    waiting_on: str = Field(default='',max_length=500)
    target_date: date | None = None

class Share(Model):
    copy_id: str = Field(min_length=32,max_length=32)

class Decision(Model):
    action: Literal['accept','request_changes']
    message: str = Field(default='',max_length=2000)

class Message(Model):
    text: str = Field(min_length=1,max_length=2000)

class TicketRequest(Model):
    title: str = Field(min_length=2,max_length=160)
    description: str = Field(min_length=10,max_length=4000)
    project_id: str | None = Field(default=None,max_length=32)
    priority: Literal['low','normal','high','urgent'] = 'normal'

class Upload(Model):
    name: str = Field(min_length=1,max_length=120)
    content_base64: str = Field(min_length=1,max_length=2800000)
    project_id: str | None = Field(default=None,max_length=32)

class CaseStudy(Model):
    title: str = Field(min_length=2,max_length=160)
    service: str = Field(min_length=2,max_length=100)
    problem: str = Field(min_length=10,max_length=1000)
    solution: str = Field(min_length=10,max_length=1000)
    result: str = Field(min_length=10,max_length=1000)
    published: bool = False
    permission_confirmed: bool = False


def routers(settings, staff):
    admin = APIRouter(prefix='/api/admin/experience',dependencies=[Depends(staff)])
    portal = APIRouter(prefix='/api/client')
    pages = APIRouter()

    def row(db, table, identifier):
        # table is always an internal constant.
        item = db.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone()
        if not item: raise HTTPException(404,'Record not found')
        return dict(item)

    def active_client(db, cid):
        item = row(db,'clients',cid)
        if item['status'] != 'active': raise HTTPException(403,'Client access is unavailable. Contact VICAM.')
        return item

    def own(db, table, identifier, cid):
        item = row(db,table,identifier)
        if item['client_id'] != cid: raise HTTPException(404,'Record not found')
        return item

    def client_session(request: Request):
        token = request.cookies.get(COOKIE,'')
        with connect(settings.db_path) as db:
            item = db.execute('''SELECT s.*,a.client_id,a.email,a.id AS account_id FROM portal_sessions s
              JOIN portal_accounts a ON a.id=s.account_id JOIN clients c ON c.id=a.client_id
              WHERE s.token_hash=? AND s.expires>? AND a.enabled=1 AND c.status='active' ''',(token_hash(token),int(time.time()))).fetchone()
        if not item: raise HTTPException(401,'Sign in to your client account')
        if request.method not in {'GET','HEAD'}:
            csrf = request.headers.get('x-csrf-token','')
            if not csrf.isascii() or not hmac.compare_digest(csrf,item['csrf']): raise HTTPException(403,'Reload the portal and try again')
        return dict(item)

    def issue_session(db, account, response):
        token,csrf = secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        seconds = settings.session_hours*3600
        db.execute('DELETE FROM portal_sessions WHERE expires<?',(int(time.time()),))
        db.execute('INSERT INTO portal_sessions VALUES(?,?,?,?)',(token_hash(token),account['id'],csrf,int(time.time())+seconds))
        response.set_cookie(COOKIE,token,max_age=seconds,httponly=True,secure=settings.secure_cookie,samesite='strict',path='/')
        return {'csrf':csrf,'email':account['email']}

    @pages.get('/client')
    def client_page(): return FileResponse(ROOT/'static/client.html')

    @pages.get('/admin/client-experience')
    def staff_page(): return FileResponse(ROOT/'static/experience.html')

    @admin.get('/clients/{cid}/access')
    def access(cid: str):
        with connect(settings.db_path) as db:
            row(db,'clients',cid)
            return {'accounts':[dict(x) for x in db.execute('SELECT id,email,enabled FROM portal_accounts WHERE client_id=?',(cid,))],
              'pending_invites':[dict(x) for x in db.execute('SELECT email,expires FROM portal_invites WHERE client_id=? AND used_at IS NULL AND expires>?',(cid,int(time.time())))]}

    @admin.post('/clients/{cid}/invite',status_code=201)
    def invite(cid: str, data: Invite, user=Depends(staff)):
        email = str(data.email).lower(); token = secrets.token_urlsafe(32)
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');active_client(db,cid)
            account = db.execute('SELECT * FROM portal_accounts WHERE email=?',(email,)).fetchone()
            if account and account['client_id'] != cid: raise HTTPException(409,'Email already belongs to another client account')
            # A fresh invitation can also reset a forgotten password. Revoke old sessions on activation.
            db.execute('DELETE FROM portal_invites WHERE email=?',(email,))
            db.execute('INSERT INTO portal_invites VALUES(?,?,?,?,NULL)',(token_hash(token),cid,email,int(time.time())+86400))
            if data.send_email:
                from .delivery import queue
                queue(db,settings,'invite',cid,email,{'token':token})
            audit(db,user['staff_id'],'invite_client',cid)
        return {'activation_url':settings.origin+'/client#invite='+token,'expires_in_hours':24,
                'email_queued':data.send_email,'message':'Send privately to the verified client contact. This link permits account setup or password reset.'}

    @admin.post('/clients/{cid}/revoke-access')
    def revoke_access(cid: str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            row(db,'clients',cid)
            db.execute('UPDATE portal_accounts SET enabled=0 WHERE client_id=?',(cid,))
            db.execute('DELETE FROM portal_sessions WHERE account_id IN (SELECT id FROM portal_accounts WHERE client_id=?)',(cid,))
            db.execute('DELETE FROM portal_invites WHERE client_id=?',(cid,))
            audit(db,user['staff_id'],'revoke_client_access',cid)
        return {'ok':True}

    @portal.post('/activate')
    def activate(data: Activation,request: Request,response: Response):
        rate_limit(settings.db_path,'client-activate',request.client.host if request.client else 'unknown',10,900)
        hashed = hash_password(data.password)
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            invite = db.execute('SELECT * FROM portal_invites WHERE token_hash=? AND used_at IS NULL AND expires>?',(token_hash(data.token),int(time.time()))).fetchone()
            if not invite: raise HTTPException(400,'Invitation has expired or was already used. Ask VICAM for a new link.')
            active_client(db,invite['client_id'])
            account = db.execute('SELECT * FROM portal_accounts WHERE email=?',(invite['email'],)).fetchone()
            if account and account['client_id'] != invite['client_id']: raise HTTPException(409,'Account setup unavailable')
            identifier = account['id'] if account else uuid.uuid4().hex
            db.execute('INSERT INTO portal_accounts VALUES(?,?,?,?,1) ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,enabled=1',
                       (identifier,invite['client_id'],invite['email'],hashed))
            db.execute('DELETE FROM portal_sessions WHERE account_id=?',(identifier,))
            db.execute('UPDATE portal_invites SET used_at=? WHERE token_hash=?',(now(),invite['token_hash']))
            audit(db,None,'client_account_activated',identifier)
            return issue_session(db,{'id':identifier,'email':invite['email']},response)

    @portal.post('/login')
    def login(data: PortalLogin,request: Request,response: Response):
        email=str(data.email).lower();ip=request.client.host if request.client else 'unknown'
        rate_limit(settings.db_path,'client-login-ip',ip,30,900)
        rate_limit(settings.db_path,'client-login-account',email,5,900)
        with connect(settings.db_path) as db:
            account = db.execute("SELECT a.* FROM portal_accounts a JOIN clients c ON c.id=a.client_id WHERE a.email=? AND a.enabled=1 AND c.status='active'",(email,)).fetchone()
            valid=check_password(data.password,account['password_hash'] if account else DUMMY_HASH)
            if not valid or not account: raise HTTPException(401,'Email or password is incorrect')
            return issue_session(db,account,response)

    @portal.get('/me')
    def me(user=Depends(client_session)):
        with connect(settings.db_path) as db:
            client=active_client(db,user['client_id'])
        return {'email':user['email'],'csrf':user['csrf'],'name':client['name'],'organization':client['organization']}

    @portal.post('/logout')
    def logout(response:Response,user=Depends(client_session)):
        with connect(settings.db_path) as db: db.execute('DELETE FROM portal_sessions WHERE token_hash=?',(user['token_hash'],))
        response.delete_cookie(COOKIE,path='/',secure=settings.secure_cookie,httponly=True,samesite='strict')
        return {'ok':True}

    @admin.put('/projects/{pid}/progress')
    def progress(pid:str,data:Progress,user=Depends(staff)):
        with connect(settings.db_path) as db:
            row(db,'projects',pid)
            v=data.model_dump(mode='json')
            db.execute('''INSERT INTO project_progress VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET
               stage=excluded.stage,summary=excluded.summary,next_milestone=excluded.next_milestone,
               waiting_on=excluded.waiting_on,target_date=excluded.target_date,updated_at=excluded.updated_at''',
               (pid,v['stage'],v['summary'],v['next_milestone'],v['waiting_on'],v['target_date'],now()))
            audit(db,user['staff_id'],'publish_project_progress',pid)
        return {'ok':True}

    @admin.get('/projects/{pid}/progress')
    def get_progress(pid:str):
        with connect(settings.db_path) as db:
            row(db,'projects',pid)
            item=db.execute('SELECT * FROM project_progress WHERE project_id=?',(pid,)).fetchone()
        return dict(item) if item else None

    @admin.delete('/projects/{pid}/progress')
    def unpublish_progress(pid:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('DELETE FROM project_progress WHERE project_id=?',(pid,))
            audit(db,user['staff_id'],'unpublish_project_progress',pid)
        return {'ok':True}

    @portal.get('/projects')
    def projects(user=Depends(client_session)):
        with connect(settings.db_path) as db:
            return {'items':[dict(x) for x in db.execute('''SELECT p.id,p.reference,p.title,p.status,g.stage,g.summary,
              g.next_milestone,g.waiting_on,g.target_date,g.updated_at FROM projects p JOIN project_progress g ON g.project_id=p.id WHERE p.client_id=? ORDER BY g.updated_at DESC''',(user['client_id'],))]}

    def shared_copy(db,copy_id,cid):
        item=db.execute('''SELECT c.*,p.signing_mode,p.pdf_sha256 FROM portal_documents s JOIN document_copies c ON c.id=s.copy_id
          JOIN pdf_artifacts p ON p.copy_id=c.id WHERE s.copy_id=? AND s.client_id=? AND c.revoked_at IS NULL''',(copy_id,cid)).fetchone()
        if not item: raise HTTPException(404,'Document unavailable')
        current=own(db,item['kind'],item['record_id'],cid)
        if current['status'] in {'draft','void'}: raise HTTPException(404,'Document unavailable')
        original=json.loads(item['snapshot_json'])
        if checksum(original)!=item['checksum']: raise HTTPException(409,'Document unavailable')
        return dict(item),original,current

    @admin.post('/clients/{cid}/documents',status_code=201)
    def share_document(cid:str,data:Share,user=Depends(staff)):
        with connect(settings.db_path) as db:
            active_client(db,cid)
            copy=row(db,'document_copies',data.copy_id)
            item=own(db,copy['kind'],copy['record_id'],cid)
            allowed={'sent','accepted'} if copy['kind']=='quotes' else {'issued'}
            original=json.loads(copy['snapshot_json'])
            if copy['revoked_at'] or item['status'] not in allowed or checksum(original)!=copy['checksum'] or checksum(terms(snapshot(db,copy['kind'],copy['record_id'],settings)))!=checksum(terms(original)):
                raise HTTPException(409,'Issue a current PDF for a sent quotation or issued invoice before sharing')
            if not db.execute('SELECT 1 FROM pdf_artifacts WHERE copy_id=?',(data.copy_id,)).fetchone(): raise HTTPException(409,'Generate the original PDF first')
            db.execute('INSERT INTO portal_documents VALUES(?,?,?) ON CONFLICT(copy_id) DO NOTHING',(data.copy_id,cid,now()))
            audit(db,user['staff_id'],'share_client_document',data.copy_id)
        return {'ok':True}

    @admin.delete('/clients/{cid}/documents/{copy_id}')
    def unshare_document(cid:str,copy_id:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('DELETE FROM portal_documents WHERE copy_id=? AND client_id=?',(copy_id,cid))
            audit(db,user['staff_id'],'unshare_client_document',copy_id)
        return {'ok':True}

    @portal.get('/documents')
    def documents(user=Depends(client_session)):
        out=[]
        with connect(settings.db_path) as db:
            ids=db.execute('SELECT copy_id FROM portal_documents WHERE client_id=? ORDER BY shared_at DESC',(user['client_id'],)).fetchall()
            for identifier in ids:
                try:item,original,current=shared_copy(db,identifier[0],user['client_id'])
                except HTTPException: continue
                decisions=[dict(x) for x in db.execute('SELECT action,message,created_at FROM quote_decisions WHERE copy_id=? ORDER BY created_at,id',(identifier[0],))]
                live=snapshot(db,item['kind'],item['record_id'],settings)
                today=datetime.now(ZoneInfo(settings.business_timezone)).date().isoformat()
                expired=bool(current['due_date'] and current['due_date']<today)
                unchanged=checksum(live)==item['checksum']
                status_only_change=canonical({k:v for k,v in live.items() if k!='status'})==canonical({k:v for k,v in original.items() if k!='status'})
                can_respond=item['kind']=='quotes' and current['status']=='sent' and unchanged and not expired
                original['source_status']=current['status']
                out.append({'id':item['id'],'snapshot':original,'issued_at':item['created_at'],'signing_mode':item['signing_mode'],
                  'superseded':not unchanged,'status_only_change':status_only_change,'can_respond':can_respond,'expired':expired,'decisions':decisions,'download_url':'/api/client/documents/'+item['id']+'/pdf',
                  'live_paid_minor':live.get('paid_minor'),'live_balance_minor':live.get('balance_minor')})
        return {'items':out}

    @portal.get('/documents/{copy_id}/pdf')
    def pdf(copy_id:str,user=Depends(client_session)):
        with connect(settings.db_path) as db:
            shared_copy(db,copy_id,user['client_id'])
            artifact=db.execute('SELECT * FROM pdf_artifacts WHERE copy_id=?',(copy_id,)).fetchone()
        if hashlib.sha256(artifact['pdf_bytes']).hexdigest()!=artifact['pdf_sha256']: raise HTTPException(409,'Original PDF unavailable')
        return Response(artifact['pdf_bytes'],media_type='application/pdf',headers={'Content-Disposition':'attachment; filename=VICAM-'+copy_id[:8]+'.pdf'})

    @portal.post('/documents/{copy_id}/decision',status_code=201)
    def decision(copy_id:str,data:Decision,user=Depends(client_session)):
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');item,original,current=shared_copy(db,copy_id,user['client_id'])
            if item['kind']!='quotes': raise HTTPException(422,'Only quotations can be approved')
            previous=db.execute("SELECT * FROM quote_decisions WHERE copy_id=? AND action='accept'",(copy_id,)).fetchone()
            if previous:
                if data.action=='accept': return {'reference':current['reference'],'message':'This quotation was already accepted.','accepted_at':previous['created_at']}
                raise HTTPException(409,'This quotation has already been accepted. Contact VICAM about changes.')
            live=snapshot(db,'quotes',item['record_id'],settings)
            if current['status']!='sent' or checksum(live)!=item['checksum']: raise HTTPException(409,'This quotation has changed. Ask VICAM for the current copy.')
            today=datetime.now(ZoneInfo(settings.business_timezone)).date().isoformat()
            if current['due_date'] and current['due_date']<today: raise HTTPException(409,'This quotation has expired. Ask VICAM for a current quotation.')
            if data.action=='request_changes' and not data.message: raise HTTPException(422,'Describe the changes you need')
            stamp=now();identifier=uuid.uuid4().hex
            db.execute('INSERT INTO quote_decisions VALUES(?,?,?,?,?,?,?,?)',(identifier,copy_id,user['client_id'],user['account_id'],data.action,data.message,item['checksum'],stamp))
            if data.action=='accept': db.execute("UPDATE quotes SET status='accepted',updated_at=? WHERE id=?",(stamp,item['record_id']))
            audit(db,None,'client_quote_'+data.action,identifier)
        return {'reference':current['reference'],'message':'Quotation accepted. VICAM will confirm the next steps.' if data.action=='accept' else 'Change request received by VICAM.','accepted_at':stamp if data.action=='accept' else None}

    @admin.get('/decisions')
    def decisions(client_id:str):
        with connect(settings.db_path) as db:
            return {'items':[dict(x) for x in db.execute('''SELECT d.action,d.message,d.created_at,d.copy_id,q.reference,a.email FROM quote_decisions d
              JOIN document_copies c ON c.id=d.copy_id JOIN quotes q ON q.id=c.record_id JOIN portal_accounts a ON a.id=d.account_id
              WHERE d.client_id=? AND q.client_id=? ORDER BY d.created_at DESC''',(client_id,client_id))]}

    @portal.get('/tickets')
    def tickets(user=Depends(client_session)):
        with connect(settings.db_path) as db:
            # Internal ticket descriptions/assignment are not exposed. Conversations are explicit public messages.
            return {'items':[dict(x) for x in db.execute('SELECT id,reference,title,status,priority,created_at,updated_at FROM tickets WHERE client_id=? ORDER BY updated_at DESC',(user['client_id'],))]}

    @portal.post('/tickets',status_code=201)
    def new_ticket(data:TicketRequest,user=Depends(client_session)):
        rate_limit(settings.db_path,'client-ticket',user['account_id'],20,3600)
        identifier=uuid.uuid4().hex;reference='TKT-'+uuid.uuid4().hex[:10].upper();stamp=now()
        with connect(settings.db_path) as db:
            if data.project_id: own(db,'projects',data.project_id,user['client_id'])
            db.execute('INSERT INTO tickets VALUES(?,?,?,?,?,?,?,NULL,?,?,?)',(identifier,reference,user['client_id'],data.project_id,data.title,'Submitted through client portal','open',data.priority,stamp,stamp))
            db.execute('INSERT INTO ticket_messages VALUES(?,?,?,?,?)',(uuid.uuid4().hex,identifier,'client',data.description,stamp))
            audit(db,None,'client_create_ticket',identifier)
        return {'id':identifier,'reference':reference,'message':'Request received. Follow updates here.'}

    def messages(db,tid):
        return {'items':[dict(x) for x in db.execute('SELECT id,author,text,created_at FROM ticket_messages WHERE ticket_id=? ORDER BY created_at,id',(tid,))]}

    @portal.get('/tickets/{tid}/messages')
    def client_messages(tid:str,user=Depends(client_session)):
        with connect(settings.db_path) as db:
            own(db,'tickets',tid,user['client_id']);return messages(db,tid)

    @admin.get('/tickets/{tid}/messages')
    def staff_messages(tid:str):
        with connect(settings.db_path) as db:
            row(db,'tickets',tid);return messages(db,tid)

    def add_message(db,tid,text,author):
        identifier=uuid.uuid4().hex;stamp=now()
        db.execute('INSERT INTO ticket_messages VALUES(?,?,?,?,?)',(identifier,tid,author,text,stamp))
        db.execute('UPDATE tickets SET updated_at=? WHERE id=?',(stamp,tid))
        return {'ok':True}

    @portal.post('/tickets/{tid}/messages',status_code=201)
    def client_reply(tid:str,data:Message,user=Depends(client_session)):
        rate_limit(settings.db_path,'client-message',user['account_id'],60,3600)
        with connect(settings.db_path) as db:
            own(db,'tickets',tid,user['client_id'])
            result=add_message(db,tid,data.text,'client');audit(db,None,'client_ticket_reply',tid)
            return result

    @admin.post('/tickets/{tid}/messages',status_code=201)
    def staff_reply(tid:str,data:Message,user=Depends(staff)):
        with connect(settings.db_path) as db:
            row(db,'tickets',tid);result=add_message(db,tid,data.text,'VICAM')
            audit(db,user['staff_id'],'client_visible_ticket_reply',tid);return result

    def upload_file(db,cid,data,author):
        active_client(db,cid)
        if data.project_id: own(db,'projects',data.project_id,cid)
        if not re.fullmatch(r'[\w .()\-]{1,120}',data.name) or data.name.startswith('.') or '..' in data.name: raise HTTPException(422,'Use a simple filename without folders')
        ext=data.name.rsplit('.',1)[-1].lower()
        mime={'pdf':'application/pdf','png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','txt':'text/plain'}.get(ext)
        if not mime: raise HTTPException(422,'Use a PDF, PNG, JPG or plain text file')
        try: content=base64.b64decode(data.content_base64,validate=True)
        except (ValueError,binascii.Error): raise HTTPException(422,'Invalid file encoding')
        if not content or len(content)>MAX_FILE: raise HTTPException(413,'Maximum file size is 2 MB')
        valid = (ext=='pdf' and content.startswith(b'%PDF-')) or (ext=='png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or (ext in {'jpg','jpeg'} and content.startswith(b'\xff\xd8\xff'))
        if ext=='txt':
            try:content.decode('utf-8');valid=b'\x00' not in content
            except UnicodeDecodeError: valid=False
        if not valid: raise HTTPException(422,'File content does not match its type')
        size=db.execute('SELECT COALESCE(sum(length(content)),0) FROM client_files WHERE client_id=?',(cid,)).fetchone()[0]
        if size+len(content)>50*1024*1024: raise HTTPException(409,'Client file allowance reached. Ask VICAM to review stored files.')
        identifier=uuid.uuid4().hex
        db.execute('INSERT INTO client_files VALUES(?,?,?,?,?,?,?,?,?)',(identifier,cid,data.project_id,data.name,mime,content,hashlib.sha256(content).hexdigest(),author,now()))
        return {'id':identifier,'message':'File shared securely with the project team.'}

    def files(db,cid):
        return {'items':[dict(x) for x in db.execute('''SELECT f.id,f.name,f.project_id,f.mime,length(f.content) AS size,f.sha256,f.uploaded_by,f.created_at FROM client_files f
          LEFT JOIN projects p ON p.id=f.project_id WHERE f.client_id=? AND (f.project_id IS NULL OR p.client_id=f.client_id) ORDER BY f.created_at DESC''',(cid,))]}

    @portal.get('/files')
    def client_files(user=Depends(client_session)):
        with connect(settings.db_path) as db:return files(db,user['client_id'])

    @admin.get('/clients/{cid}/files')
    def staff_files(cid:str):
        with connect(settings.db_path) as db:row(db,'clients',cid);return files(db,cid)

    @portal.post('/files',status_code=201)
    def client_upload(data:Upload,user=Depends(client_session)):
        rate_limit(settings.db_path,'client-upload',user['account_id'],20,3600)
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');result=upload_file(db,user['client_id'],data,'client')
            audit(db,None,'client_upload_file',result['id']);return result

    @admin.post('/clients/{cid}/files',status_code=201)
    def staff_upload(cid:str,data:Upload,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');result=upload_file(db,cid,data,'VICAM')
            audit(db,user['staff_id'],'share_client_file',result['id']);return result

    def download_file(db,fid,cid=None):
        item=row(db,'client_files',fid)
        if cid and item['client_id']!=cid: raise HTTPException(404,'File not found')
        if item['project_id']:own(db,'projects',item['project_id'],item['client_id'])
        if hashlib.sha256(item['content']).hexdigest()!=item['sha256']: raise HTTPException(409,'File unavailable')
        # Always download, never render uploaded active content on this origin.
        safe=''.join(c if c.isascii() and (c.isalnum() or c in ' .()-_') else '_' for c in item['name'])
        return Response(item['content'],media_type='application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+safe+'"'})

    @portal.get('/files/{fid}/download')
    def client_download(fid:str,user=Depends(client_session)):
        with connect(settings.db_path) as db:return download_file(db,fid,user['client_id'])

    @admin.get('/files/{fid}/download')
    def staff_download(fid:str):
        with connect(settings.db_path) as db:return download_file(db,fid)

    @admin.delete('/files/{fid}')
    def remove_file(fid:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            row(db,'client_files',fid);db.execute('DELETE FROM client_files WHERE id=?',(fid,))
            audit(db,user['staff_id'],'remove_client_file',fid)
        return {'ok':True}

    @admin.get('/follow-ups')
    def followups(user=Depends(staff)):
        today=datetime.now(ZoneInfo(settings.business_timezone)).date();cutoff=(today-timedelta(days=2)).isoformat();items=[]
        with connect(settings.db_path) as db:
            for x in db.execute("SELECT id,reference,name,created_at FROM enquiries WHERE status='new' AND date(created_at)<=? ORDER BY created_at",(cutoff,)):
                items.append({'kind':'enquiry','reference':x['reference'],'title':'Reply to '+x['name'],'due':x['created_at'][:10],'url':'/admin?enquiry='+x['id']})
            for x in db.execute("SELECT id,reference,title,client_id,due_date FROM tasks WHERE status='open' AND due_date<=? ORDER BY due_date",(today.isoformat(),)):
                items.append({'kind':'task','reference':x['reference'],'title':x['title'],'due':x['due_date'],'url':'/admin/clients?kind=tasks&record='+x['id']})
            for x in db.execute("SELECT id,reference,title,due_date FROM quotes WHERE status='sent' AND (date(updated_at)<=? OR due_date<=?)",((today-timedelta(days=7)).isoformat(),today.isoformat())):
                items.append({'kind':'quotation','reference':x['reference'],'title':'Follow up: '+x['title'],'due':x['due_date'],'url':'/admin/clients?kind=quotes&record='+x['id']})
            for x in db.execute("SELECT i.id,i.reference,i.title,i.due_date,i.currency,i.amount_minor-COALESCE(sum(p.amount_minor),0) AS balance_minor FROM invoices i LEFT JOIN payments p ON p.invoice_id=i.id WHERE i.status='issued' AND i.due_date<? GROUP BY i.id HAVING balance_minor>0",(today.isoformat(),)):
                items.append({'kind':'invoice','reference':x['reference'],'title':'Payment follow-up: '+x['title'],'due':x['due_date'],'balance_minor':x['balance_minor'],'currency':x['currency'],'url':'/admin/clients?kind=invoices&record='+x['id']})
            for x in db.execute("SELECT id,reference,title,end_date FROM contracts WHERE status='active' AND end_date<=?",((today+timedelta(days=30)).isoformat(),)):
                items.append({'kind':'contract','reference':x['reference'],'title':'Review renewal: '+x['title'],'due':x['end_date'],'url':'/admin/clients?kind=contracts&record='+x['id']})
            for x in db.execute("SELECT id,client_id,name,warranty_until FROM equipment WHERE status<>'retired' AND warranty_until BETWEEN ? AND ?",(today.isoformat(),(today+timedelta(days=30)).isoformat())):
                items.append({'kind':'warranty','reference':x['id'][:8].upper(),'title':'Warranty ending: '+x['name'],'due':x['warranty_until'],'url':'/admin/service-records?client='+x['client_id']})
        if user['role']=='support':items=[x for x in items if x['kind'] not in {'quotation','invoice'}]
        return {'items':items,'message':'Dashboard follow-ups. Client email reminders require opt-in and the separate reminder job.'}

    @admin.get('/case-studies')
    def case_studies():
        with connect(settings.db_path) as db:return {'items':[dict(x) for x in db.execute('SELECT * FROM case_studies ORDER BY created_at DESC')]}

    @admin.post('/case-studies',status_code=201)
    def add_case(data:CaseStudy,user=Depends(staff)):
        if data.published and not data.permission_confirmed:raise HTTPException(422,'Confirm permission to publish this real project example')
        v=data.model_dump();identifier=uuid.uuid4().hex
        with connect(settings.db_path) as db:
            db.execute('INSERT INTO case_studies VALUES(?,?,?,?,?,?,?,?,?)',(identifier,v['title'],v['service'],v['problem'],v['solution'],v['result'],int(v['published']),int(v['permission_confirmed']),now()))
            audit(db,user['staff_id'],'create_case_study',identifier)
        return {'id':identifier}

    @admin.put('/case-studies/{identifier}')
    def edit_case(identifier:str,data:CaseStudy,user=Depends(staff)):
        if data.published and not data.permission_confirmed:raise HTTPException(422,'Confirm permission to publish this real project example')
        v=data.model_dump()
        with connect(settings.db_path) as db:
            row(db,'case_studies',identifier)
            db.execute('UPDATE case_studies SET title=?,service=?,problem=?,solution=?,result=?,published=?,permission_confirmed=? WHERE id=?',
              (v['title'],v['service'],v['problem'],v['solution'],v['result'],int(v['published']),int(v['permission_confirmed']),identifier))
            audit(db,user['staff_id'],'update_case_study',identifier)
        return {'ok':True}

    @admin.delete('/case-studies/{identifier}')
    def delete_case(identifier:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            row(db,'case_studies',identifier);db.execute('DELETE FROM case_studies WHERE id=?',(identifier,))
            audit(db,user['staff_id'],'delete_case_study',identifier)
        return {'ok':True}

    @pages.get('/api/public/case-studies')
    def public_cases():
        with connect(settings.db_path) as db:return {'items':[dict(x) for x in db.execute('SELECT title,service,problem,solution,result FROM case_studies WHERE published=1 AND permission_confirmed=1 ORDER BY created_at DESC')]}

    from .service_records import install
    install(admin,portal,pages,settings,staff,client_session)
    return admin,portal,pages
