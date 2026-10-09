"""Equipment register, immutable published visit reports and client acknowledgements."""
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .config import ROOT
from .db import connect, now, audit

SCHEMA = '''
CREATE TABLE IF NOT EXISTS equipment(id TEXT PRIMARY KEY,client_id TEXT NOT NULL REFERENCES clients(id),project_id TEXT REFERENCES projects(id),name TEXT NOT NULL,category TEXT NOT NULL,manufacturer TEXT NOT NULL,model TEXT NOT NULL,serial_number TEXT NOT NULL,location TEXT NOT NULL,installed_on TEXT,warranty_until TEXT,status TEXT NOT NULL,notes TEXT NOT NULL,shared INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS equipment_client ON equipment(client_id);
CREATE TABLE IF NOT EXISTS service_reports(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id),project_id TEXT REFERENCES projects(id),equipment_id TEXT REFERENCES equipment(id),visit_date TEXT NOT NULL,technician TEXT NOT NULL,work_done TEXT NOT NULL,findings TEXT NOT NULL,next_steps TEXT NOT NULL,status TEXT NOT NULL,content_hash TEXT NOT NULL,created_by INTEGER NOT NULL REFERENCES staff(id),created_at TEXT NOT NULL,shared_at TEXT,acknowledged_at TEXT,acknowledged_by INTEGER REFERENCES portal_accounts(id),acknowledgement_note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS reports_client ON service_reports(client_id);
'''
class Model(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class Equipment(Model):
    client_id:str=Field(min_length=32,max_length=32)
    project_id:str|None=Field(default=None,min_length=32,max_length=32)
    name:str=Field(min_length=2,max_length=160)
    category:Literal['camera','recorder','computer','network','access_control','other']='other'
    manufacturer:str=Field(default='',max_length=100)
    model:str=Field(default='',max_length=100)
    serial_number:str=Field(default='',max_length=160)
    location:str=Field(default='',max_length=200)
    installed_on:date|None=None
    warranty_until:date|None=None
    status:Literal['active','repair','retired']='active'
    notes:str=Field(default='',max_length=2000)
    shared:bool=Field(default=False,strict=True)
    @model_validator(mode='after')
    def dates(self):
        if self.installed_on and self.warranty_until and self.warranty_until<self.installed_on:raise ValueError('Warranty date cannot precede installation')
        return self
class Report(Model):
    client_id:str=Field(min_length=32,max_length=32)
    project_id:str|None=Field(default=None,min_length=32,max_length=32)
    equipment_id:str|None=Field(default=None,min_length=32,max_length=32)
    visit_date:date
    technician:str=Field(min_length=2,max_length=120)
    work_done:str=Field(min_length=10,max_length=4000)
    findings:str=Field(default='',max_length=2000)
    next_steps:str=Field(default='',max_length=2000)
class Acknowledgement(Model):
    confirmed:bool=Field(strict=True)
    note:str=Field(default='',max_length=2000)

def install(admin,portal,pages,settings,staff,client_session):
    def get(db,table,id):
        r=db.execute(f'SELECT * FROM {table} WHERE id=?',(id,)).fetchone()
        if not r:raise HTTPException(404,'Record not found')
        return dict(r)
    def links(db,v):
        get(db,'clients',v['client_id'])
        for key,table in [('project_id','projects'),('equipment_id','equipment')]:
            if v.get(key) and get(db,table,v[key])['client_id']!=v['client_id']:raise HTTPException(409,'Choose records belonging to this client')
        if v.get('equipment_id') and v.get('project_id'):
            asset=get(db,'equipment',v['equipment_id'])
            if asset['project_id'] and asset['project_id']!=v['project_id']:raise HTTPException(409,'The equipment belongs to a different project')
    def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def equipment_public(v):return {k:x for k,x in v.items() if k not in {'notes','shared'}}
    def report_public(v):return {k:x for k,x in v.items() if k not in {'created_by','acknowledged_by'}}
    def paged(db,table,cid,page,shared=False):
        where='client_id=?'+(" AND shared=1" if shared and table=='equipment' else " AND status='shared'" if shared else '')
        total=db.execute(f'SELECT count(*) FROM {table} WHERE '+where,(cid,)).fetchone()[0]
        return {'items':[dict(x) for x in db.execute(f'SELECT * FROM {table} WHERE '+where+' ORDER BY created_at DESC,id DESC LIMIT 25 OFFSET ?',(cid,(page-1)*25))],'total':total,'page':page,'page_size':25}
    @pages.get('/admin/service-records')
    def workspace():return FileResponse(ROOT/'static/service-records.html')
    @admin.get('/clients/{cid}/equipment')
    def equipment_list(cid:str,page:int=Query(1,ge=1)):
        with connect(settings.db_path) as db:
            get(db,'clients',cid);return paged(db,'equipment',cid,page)
    @admin.post('/equipment',status_code=201)
    def add_equipment(data:Equipment,user=Depends(staff)):
        v=data.model_dump(mode='json');v.update(id=uuid.uuid4().hex,created_at=now(),updated_at=now())
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');links(db,v)
            db.execute('INSERT INTO equipment('+','.join(v)+') VALUES('+','.join('?' for _ in v)+')',list(v.values()))
            audit(db,user['staff_id'],'create_equipment',v['id']);return v
    @admin.put('/equipment/{id}')
    def edit_equipment(id:str,data:Equipment,user=Depends(staff)):
        v=data.model_dump(mode='json')
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');old=get(db,'equipment',id)
            if v['client_id']!=old['client_id']:raise HTTPException(409,'Equipment must stay with its original client; retire it and create another record')
            if v['project_id']!=old['project_id'] and db.execute('SELECT 1 FROM service_reports WHERE equipment_id=?',(id,)).fetchone():raise HTTPException(409,'Equipment with reports must retain its project')
            links(db,v);v['updated_at']=now()
            db.execute('UPDATE equipment SET '+','.join(k+'=?' for k in v)+' WHERE id=?',[*v.values(),id])
            audit(db,user['staff_id'],'update_equipment',id);return get(db,'equipment',id)
    @admin.get('/clients/{cid}/reports')
    def report_list(cid:str,page:int=Query(1,ge=1)):
        with connect(settings.db_path) as db:
            get(db,'clients',cid);result=paged(db,'service_reports',cid,page)
            for item in result['items']:
                account=db.execute('SELECT email FROM portal_accounts WHERE id=?',(item['acknowledged_by'],)).fetchone()
                item['acknowledged_email']=account['email'] if account else None
            return result
    @admin.post('/reports',status_code=201)
    def add_report(data:Report,user=Depends(staff)):
        v=data.model_dump(mode='json');v.update(id=uuid.uuid4().hex,reference='VIS-'+uuid.uuid4().hex[:10].upper(),status='draft',content_hash='',created_by=user['staff_id'],created_at=now())
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');links(db,v)
            db.execute('INSERT INTO service_reports('+','.join(v)+') VALUES('+','.join('?' for _ in v)+')',list(v.values()))
            audit(db,user['staff_id'],'create_service_report',v['reference']);return get(db,'service_reports',v['id'])
    @admin.put('/reports/{id}')
    def edit_report(id:str,data:Report,user=Depends(staff)):
        v=data.model_dump(mode='json')
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');old=get(db,'service_reports',id)
            if old['status']!='draft':raise HTTPException(409,'Published reports are locked. Create a new correction report.')
            if old['client_id']!=v['client_id']:raise HTTPException(409,'Reports must stay with their original client')
            links(db,v);db.execute('UPDATE service_reports SET '+','.join(k+'=?' for k in v)+' WHERE id=?',[*v.values(),id]);audit(db,user['staff_id'],'edit_service_report',old['reference']);return get(db,'service_reports',id)
    @admin.post('/reports/{id}/share')
    def share_report(id:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');v=get(db,'service_reports',id);links(db,v)
            if get(db,'clients',v['client_id'])['status']!='active':raise HTTPException(409,'Activate the client before sharing')
            if v['status']=='draft':
                content={k:v[k] for k in Report.model_fields};content.update(reference=v['reference'])
                db.execute("UPDATE service_reports SET status='shared',shared_at=?,content_hash=? WHERE id=?",(now(),digest(content),id));audit(db,user['staff_id'],'share_service_report',v['reference'])
            return get(db,'service_reports',id)
    @portal.get('/equipment')
    def client_equipment(page:int=Query(1,ge=1),user=Depends(client_session)):
        with connect(settings.db_path) as db:
            result=paged(db,'equipment',user['client_id'],page,True);result['items']=[equipment_public(x) for x in result['items']];return result
    @portal.get('/reports')
    def client_reports(page:int=Query(1,ge=1),user=Depends(client_session)):
        with connect(settings.db_path) as db:
            result=paged(db,'service_reports',user['client_id'],page,True);result['items']=[report_public(x) for x in result['items']];return result
    @portal.post('/reports/{id}/acknowledge')
    def acknowledge(id:str,data:Acknowledgement,user=Depends(client_session)):
        if not data.confirmed:raise HTTPException(422,'Confirm that you have reviewed this service report')
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');v=get(db,'service_reports',id)
            if v['client_id']!=user['client_id'] or v['status']!='shared':raise HTTPException(404,'Record not found')
            if not v['acknowledged_at']:
                db.execute('UPDATE service_reports SET acknowledged_at=?,acknowledged_by=?,acknowledgement_note=? WHERE id=?',(now(),user['account_id'],data.note,id))
                audit(db,None,'acknowledge_service_report',v['reference'])
            return report_public(get(db,'service_reports',id))
    @admin.get('/clients/{cid}/timeline')
    def timeline(cid:str,page:int=Query(1,ge=1),user=Depends(staff)):
        with connect(settings.db_path) as db:
            get(db,'clients',cid)
            parts=[];args=[]
            for table,title,status in [('projects','title','status'),('tasks','title','status'),('quotes','title','status'),('invoices','title','status'),('tickets','title','status'),('contracts','title','status'),('equipment','name','status'),('service_reports','reference','status')]:
                if user['role']=='support' and table in {'quotes','invoices'}:continue
                parts.append(f"SELECT id,'{table}' kind,{title} title,{status} status,created_at occurred_at FROM {table} WHERE client_id=?");args.append(cid)
            parts.extend(["SELECT p.id,'payments' kind,i.reference title,p.method status,p.created_at occurred_at FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE i.client_id=?","SELECT e.id,'enquiries' kind,e.reference title,e.status status,e.created_at occurred_at FROM enquiries e JOIN enquiry_clients l ON l.enquiry_id=e.id WHERE l.client_id=?","SELECT d.id,'quotation_decision' kind,c.reference title,d.action status,d.created_at occurred_at FROM quote_decisions d JOIN quotes c ON c.id=(SELECT record_id FROM document_copies WHERE id=d.copy_id) WHERE d.client_id=?","SELECT id,'report_acknowledgement' kind,reference title,'acknowledged' status,acknowledged_at occurred_at FROM service_reports WHERE client_id=? AND acknowledged_at IS NOT NULL"]);args.extend([cid]*4)
            if user['role']=='support':
                parts=[x for x in parts if "'payments' kind" not in x and "'quotation_decision' kind" not in x];args=[cid]*len(parts)
            parts.append("SELECT cast(n.id AS TEXT) id,'team_note' kind,'Team note added' title,'private' status,n.created_at occurred_at FROM notes n JOIN enquiry_clients l ON l.enquiry_id=n.enquiry_id WHERE l.client_id=?");args.append(cid)
            parts.append("SELECT p.id,'project_update' kind,p.title title,g.stage status,g.updated_at occurred_at FROM project_progress g JOIN projects p ON p.id=g.project_id WHERE p.client_id=?");args.append(cid)
            sql=' UNION ALL '.join(parts);total=db.execute('SELECT count(*) FROM ('+sql+')',args).fetchone()[0]
            items=[dict(x) for x in db.execute('SELECT * FROM ('+sql+') ORDER BY occurred_at DESC,id DESC LIMIT 25 OFFSET ?',[*args,(page-1)*25])]
            for item in items:
                if item['kind'] in {'equipment','service_reports','report_acknowledgement'}:item['url']='/admin/service-records?client='+cid
                elif item['kind'] in {'enquiries','team_note'}:
                    eid=item['id'] if item['kind']=='enquiries' else db.execute('SELECT enquiry_id FROM notes WHERE id=?',(item['id'],)).fetchone()[0]
                    item['url']='/admin?enquiry='+eid
                elif item['kind']=='quotation_decision':
                    qid=db.execute('SELECT c.record_id FROM document_copies c JOIN quote_decisions d ON d.copy_id=c.id WHERE d.id=?',(item['id'],)).fetchone()[0]
                    item['url']='/admin/clients?kind=quotes&record='+qid
                else:item['url']='/admin/clients?kind='+('projects' if item['kind']=='project_update' else item['kind'])+'&record='+item['id']
            return {'items':items,'total':total,'page':page,'page_size':25}
    @admin.get('/service-dashboard')
    def dashboard(user=Depends(staff)):
        today=datetime.now(ZoneInfo(settings.business_timezone)).date()
        with connect(settings.db_path) as db:
            result={'active_equipment':db.execute("SELECT count(*) FROM equipment WHERE status='active'").fetchone()[0],'equipment_in_repair':db.execute("SELECT count(*) FROM equipment WHERE status='repair'").fetchone()[0],'warranties_ending':db.execute("SELECT count(*) FROM equipment WHERE status<>'retired' AND warranty_until BETWEEN ? AND ?",(today.isoformat(),(today+timedelta(days=30)).isoformat())).fetchone()[0],'unacknowledged_reports':db.execute("SELECT count(*) FROM service_reports WHERE status='shared' AND acknowledged_at IS NULL").fetchone()[0]}
            if user['role']=='admin':
                result['pending_quotes']=db.execute("SELECT count(*) FROM quotes WHERE status='sent'").fetchone()[0]
                result['outstanding_by_currency']=[dict(x) for x in db.execute("SELECT currency,sum(balance) amount_minor FROM (SELECT i.currency,i.amount_minor-COALESCE(sum(p.amount_minor),0) balance FROM invoices i LEFT JOIN payments p ON p.invoice_id=i.id WHERE i.status='issued' GROUP BY i.id) WHERE balance>0 GROUP BY currency")]
            return result
