"""Private client management; all routes reuse staff sessions and CSRF protection."""
import sqlite3
import uuid
import json
from decimal import Decimal
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, model_validator
from .db import audit, connect, now
from .pricing import LineItem, calculate
from .operations import history

SCHEMA = '''
CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,name TEXT NOT NULL,email TEXT NOT NULL,organization TEXT NOT NULL,phone TEXT NOT NULL,notes TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS enquiry_clients(enquiry_id TEXT PRIMARY KEY REFERENCES enquiries(id) ON DELETE CASCADE,client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE RESTRICT);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id),title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,assigned_to INTEGER REFERENCES staff(id),due_date TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id),project_id TEXT REFERENCES projects(id),title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,assigned_to INTEGER REFERENCES staff(id),due_date TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id),project_id TEXT REFERENCES projects(id),title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,due_date TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id),project_id TEXT REFERENCES projects(id),title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,due_date TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,invoice_id TEXT NOT NULL REFERENCES invoices(id),amount_minor INTEGER NOT NULL,paid_date TEXT NOT NULL,method TEXT NOT NULL,external_reference TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id),project_id TEXT REFERENCES projects(id),title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,assigned_to INTEGER REFERENCES staff(id),priority TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contracts(id TEXT PRIMARY KEY,reference TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id),title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,start_date TEXT NOT NULL,end_date TEXT NOT NULL,assigned_to INTEGER REFERENCES staff(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS projects_client ON projects(client_id);
CREATE INDEX IF NOT EXISTS tasks_due ON tasks(status,due_date);
CREATE INDEX IF NOT EXISTS payments_invoice ON payments(invoice_id);
'''

class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Client(Record):
    name: str = Field(min_length=2,max_length=100)
    email: EmailStr = Field(max_length=150)
    organization: str = Field(default='',max_length=120)
    phone: str = Field(default='',max_length=40)
    notes: str = Field(default='',max_length=4000)
    status: Literal['active','archived'] = 'active'
    reminder_enabled: bool = Field(default=False,strict=True)

class Linked(Record):
    client_id: str = Field(min_length=1,max_length=32)
    title: str = Field(min_length=2,max_length=160)
    description: str = Field(default='',max_length=4000)

class Project(Linked):
    status: Literal['planned','active','on_hold','completed','cancelled'] = 'planned'
    assigned_to: int | None = Field(default=None,strict=True,ge=1)
    due_date: date | None = None

class Task(Linked):
    project_id: str | None = Field(default=None,max_length=32)
    status: Literal['open','done','cancelled'] = 'open'
    assigned_to: int | None = Field(default=None,strict=True,ge=1)
    due_date: date

class Document(Linked):
    project_id: str | None = Field(default=None,max_length=32)
    amount_minor: int | None = Field(default=None,strict=True,ge=1,le=999999999999)
    line_items: list[LineItem] = Field(default_factory=list,max_length=50)
    discount_percent: Decimal = Field(default=Decimal("0"),ge=0,le=100,max_digits=5,decimal_places=2)
    vat_percent: Decimal = Field(default=Decimal("16"),ge=0,le=100,max_digits=5,decimal_places=2)

    @model_validator(mode="after")
    def pricing_source(self):
        if not self.line_items and self.amount_minor is None:raise ValueError("Enter a total or add line items")
        return self

    currency: Literal['KES','USD','EUR','GBP'] = 'KES'
    due_date: date | None = None

class Quote(Document):
    status: Literal['draft','sent','accepted','declined','expired'] = 'draft'

class Invoice(Document):
    status: Literal['draft','issued','void'] = 'draft'

class Payment(Record):
    invoice_id: str = Field(min_length=1,max_length=32)
    amount_minor: int = Field(strict=True,ge=1,le=999999999999)
    paid_date: date
    method: Literal['bank_transfer','mpesa','cash','card','other'] = 'bank_transfer'
    external_reference: str = Field(min_length=1,max_length=100)

class Ticket(Linked):
    project_id: str | None = Field(default=None,max_length=32)
    status: Literal['open','in_progress','waiting','resolved'] = 'open'
    assigned_to: int | None = Field(default=None,strict=True,ge=1)
    priority: Literal['low','normal','high','urgent'] = 'normal'

class Contract(Linked):
    status: Literal['draft','active','ended','cancelled'] = 'draft'
    start_date: date
    end_date: date
    assigned_to: int | None = Field(default=None,strict=True,ge=1)

    @model_validator(mode='after')
    def date_order(self):
        if self.end_date < self.start_date: raise ValueError('End date must follow the start date')
        return self

class Conversion(Record):
    client_id: str | None = Field(default=None,min_length=1,max_length=32)

MODELS={'clients':Client,'projects':Project,'tasks':Task,'quotes':Quote,'invoices':Invoice,'payments':Payment,'tickets':Ticket,'contracts':Contract}
PREFIXES={'clients':'CLI','projects':'PRJ','tasks':'TSK','quotes':'QUO','invoices':'INV','payments':'PAY','tickets':'TKT','contracts':'CON'}

def router(settings, staff):
    r=APIRouter(prefix='/api/admin/crm',dependencies=[Depends(staff)])

    def business_today():
        return datetime.now(ZoneInfo(settings.business_timezone)).date()

    def kind_table(kind):
        if kind not in MODELS: raise HTTPException(404,'Unknown record type')
        return kind

    def row(db,kind,identifier):
        kind_table(kind)
        item=db.execute(f'SELECT * FROM {kind} WHERE id=?',(identifier,)).fetchone()
        if not item: raise HTTPException(404,'Record not found')
        return dict(item)

    def enrich(db,kind,item):
        if kind in {'quotes','invoices'}:
            pricing=json.loads(item.pop('pricing_json','') or '{}')
            item.update(line_items=[{k:v for k,v in x.items() if k!='line_total_minor'} for x in pricing.get('line_items',[])],discount_percent=pricing.get('discount_percent','0'),vat_percent=pricing.get('vat_percent','16'),pricing=pricing or None)
        if kind=='invoices':
            paid=db.execute('SELECT COALESCE(sum(amount_minor),0) FROM payments WHERE invoice_id=?',(item['id'],)).fetchone()[0]
            item.update(paid_minor=paid,balance_minor=item['amount_minor']-paid,payment_status='void' if item['status']=='void' else 'paid' if paid==item['amount_minor'] else 'partial' if paid else 'unpaid')
        if kind=='tasks':item['overdue']=item['status']=='open' and item['due_date']<business_today().isoformat()
        return item

    def visible(user,kind,item):
        if user['role']=='finance':
            if kind=='clients':item={k:v for k,v in item.items() if k not in {'notes','enquiries'}}
            if kind=='projects':item={k:v for k,v in item.items() if k!='description'}
        return item

    def values(kind,data):
        try:
            v=MODELS[kind].model_validate(data).model_dump(mode='json')
            if kind in {'quotes','invoices'}:
                items=v.pop('line_items');discount=v.pop('discount_percent');vat=v.pop('vat_percent')
                pricing=calculate(items,discount,vat) if items else None
                if pricing:
                    if v['amount_minor'] is not None and v['amount_minor']!=pricing['total_minor']:raise ValueError('Total differs from the calculated line items')
                    v['amount_minor']=pricing['total_minor']
                v['pricing_json']=json.dumps(pricing,sort_keys=True,separators=(',',':')) if pricing else ''
            return v
        except ValidationError as exc:
            raise HTTPException(422,[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()])
        except ValueError as exc:raise HTTPException(422,str(exc))

    def links(db,kind,v,identifier=None):
        if 'client_id' in v:row(db,'clients',v['client_id'])
        if v.get('project_id'):
            project=row(db,'projects',v['project_id'])
            if project['client_id']!=v['client_id']:raise HTTPException(409,'The project belongs to another client')
        if v.get('assigned_to') and not db.execute('SELECT 1 FROM staff WHERE id=? AND enabled=1',(v['assigned_to'],)).fetchone():raise HTTPException(409,'Choose an active staff account')
        if kind in {'projects','tickets','quotes','invoices'} and identifier:
            previous=row(db,kind,identifier)
            if v['client_id'] != previous['client_id']:
                if kind=='projects' and (db.execute('SELECT 1 FROM project_progress WHERE project_id=?',(identifier,)).fetchone() or db.execute('SELECT 1 FROM client_files WHERE project_id=?',(identifier,)).fetchone()):
                    raise HTTPException(409,'Remove shared project updates and files before changing the client')
                if kind=='tickets' and db.execute('SELECT 1 FROM ticket_messages WHERE ticket_id=?',(identifier,)).fetchone():
                    raise HTTPException(409,'A ticket with a client conversation must stay with its original client')
                if kind in {'quotes','invoices'} and db.execute('SELECT 1 FROM portal_documents s JOIN document_copies c ON c.id=s.copy_id WHERE c.kind=? AND c.record_id=?',(kind,identifier)).fetchone():
                    raise HTTPException(409,'A shared document must stay with its original client; create a new record instead')
        if kind=='projects' and identifier:
            if any(db.execute(f'SELECT 1 FROM {table} WHERE project_id=? AND client_id<>? LIMIT 1',(identifier,v['client_id'])).fetchone() for table in ('tasks','quotes','invoices','tickets','equipment','service_reports')):raise HTTPException(409,'Keep the project with the client used by its linked records')
        if kind=='invoices' and identifier:
            previous=row(db,kind,identifier)
            if db.execute('SELECT 1 FROM payments WHERE invoice_id=?',(identifier,)).fetchone() and any(v[k]!=previous[k] for k in ('amount_minor','currency','client_id','status','pricing_json')):raise HTTPException(409,'An invoice with payments cannot change amount, currency, client or status')
        if kind=='payments':
            invoice=row(db,'invoices',v['invoice_id'])
            if invoice['status']!='issued':raise HTTPException(409,'Payments can only be recorded against issued invoices')
            paid=db.execute('SELECT COALESCE(sum(amount_minor),0) FROM payments WHERE invoice_id=? AND id<>?',(v['invoice_id'],identifier or '')).fetchone()[0]
            if paid+v['amount_minor']>invoice['amount_minor']:raise HTTPException(409,'Payment exceeds the outstanding balance')
            if db.execute('SELECT 1 FROM payments WHERE invoice_id=? AND external_reference=? AND id<>?',(v['invoice_id'],v['external_reference'],identifier or '')).fetchone():raise HTTPException(409,'This payment reference is already recorded on the invoice')

    def insert(db,kind,v,user):
        identifier=uuid.uuid4().hex;stamp=now()
        v=dict(v,id=identifier,reference=PREFIXES[kind]+'-'+uuid.uuid4().hex[:10].upper(),created_at=stamp,updated_at=stamp)
        db.execute(f"INSERT INTO {kind}({','.join(v)}) VALUES({','.join('?' for _ in v)})",list(v.values()))
        history(db,user['staff_id'],kind,identifier,None,v)
        audit(db,user['staff_id'],'create_'+kind,v['reference'])
        return enrich(db,kind,v)

    @r.post('/calculate')
    def calculate_preview(data:dict):
        from pydantic import ValidationError
        try:
            model=Document.model_validate(dict(data,client_id='preview',title='Preview'))
            if not model.line_items:raise ValueError('Add at least one line item')
            return calculate(model.line_items,model.discount_percent,model.vat_percent)
        except (ValidationError,ValueError) as exc:raise HTTPException(422,'Check line items, quantities, unit prices and percentage limits')

    @r.get('/summary')
    def summary(user=Depends(staff)):
        today=business_today().isoformat()
        with connect(settings.db_path) as db:
            return {'clients':db.execute("SELECT count(*) FROM clients WHERE status='active'").fetchone()[0], 'active_projects':db.execute("SELECT count(*) FROM projects WHERE status='active'").fetchone()[0], 'due_tasks':db.execute("SELECT count(*) FROM tasks WHERE status='open' AND due_date<=?",(today,)).fetchone()[0], 'open_tickets':db.execute("SELECT count(*) FROM tickets WHERE status<>'resolved'").fetchone()[0], 'ending_contracts':db.execute("SELECT count(*) FROM contracts WHERE status='active' AND end_date<=date(?,'+30 days')",(today,)).fetchone()[0]}

    @r.get('/staff')
    def staff_options():
        with connect(settings.db_path) as db:return {'items':[dict(x) for x in db.execute('SELECT id,email FROM staff WHERE enabled=1 ORDER BY email')]}

    @r.post('/convert/{enquiry_id}')
    def convert(enquiry_id:str,data:Conversion,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT client_id FROM enquiry_clients WHERE enquiry_id=?',(enquiry_id,)).fetchone()
            if existing:
                if data.client_id and data.client_id!=existing[0]:raise HTTPException(409,'This enquiry is already linked to another client')
                return row(db,'clients',existing[0])
            enquiry=db.execute('SELECT * FROM enquiries WHERE id=?',(enquiry_id,)).fetchone()
            if not enquiry:raise HTTPException(404,'Enquiry not found')
            if data.client_id:client=row(db,'clients',data.client_id)
            else:client=insert(db,'clients',Client(name=enquiry['name'],email=enquiry['email'],organization=enquiry['organization'],phone=enquiry['phone']).model_dump(mode='json'),user)
            db.execute('INSERT INTO enquiry_clients VALUES(?,?)',(enquiry_id,client['id']))
            audit(db,user['staff_id'],'link_enquiry',enquiry['reference'])
            return client

    @r.get('/{kind}')
    def listing(kind:str,q:str=Query('',max_length=100),client_id:str|None=None,invoice_id:str|None=None,page:int=Query(1,ge=1),due_only:bool=False,assistant_filter:Literal['all','unpaid','overdue','due_today','expiring_week','active','open']='all',user=Depends(staff)):
        kind_table(kind);clauses=[];args=[]
        if q.strip():
            fields=['reference','name','email','organization'] if kind=='clients' else ['reference','external_reference'] if kind=='payments' else ['reference','title']
            term='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            clauses.append('('+' OR '.join(f"{f} LIKE ? ESCAPE '\\'" for f in fields)+')');args.extend([term]*len(fields))
        if client_id:
            if kind=='clients':clauses.append('id=?')
            elif kind=='payments':clauses.append('invoice_id IN (SELECT id FROM invoices WHERE client_id=?)')
            else:clauses.append('client_id=?')
            args.append(client_id)
        if due_only:
            if kind!='tasks':raise HTTPException(422,'Due filter is only for tasks')
            clauses.append("status='open' AND due_date<=?");args.append(business_today().isoformat())
        if assistant_filter!='all':
            supported={'due_today':{'tasks'},'unpaid':{'invoices'},'overdue':{'invoices','tasks'},'expiring_week':{'quotes','contracts'},'active':{'clients','projects','contracts'},'open':{'tasks','tickets'}}
            if kind not in supported[assistant_filter]:raise HTTPException(422,'Unsupported assistant filter for this record type')
            today=business_today()
            if assistant_filter in {'unpaid','overdue'}:
                if kind=='invoices':clauses.append("status='issued' AND amount_minor>COALESCE((SELECT sum(p.amount_minor) FROM payments p WHERE p.invoice_id=invoices.id),0)")
                else:clauses.append("status='open'")
                if assistant_filter=='overdue':clauses.append('due_date<?');args.append(today.isoformat())
            elif assistant_filter=='due_today':clauses.append("due_date=? AND status='open'");args.append(today.isoformat())
            elif assistant_filter=='expiring_week':
                from datetime import timedelta
                column='end_date' if kind=='contracts' else 'due_date'
                clauses.append(f'{column} BETWEEN ? AND ?');args.extend([today.isoformat(),(today+timedelta(days=6-today.weekday())).isoformat()]);clauses.append("status='active'" if kind=='contracts' else "status='sent'")
            elif assistant_filter=='active':clauses.append("status='active'")
            elif assistant_filter=='open':clauses.append("status<>'resolved'" if kind=='tickets' else "status='open'")
        if invoice_id:
            if kind!='payments':raise HTTPException(422,'Invoice filter is only for payments')
            clauses.append('invoice_id=?');args.append(invoice_id)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        with connect(settings.db_path) as db:
            total=db.execute(f'SELECT count(*) FROM {kind}'+where,args).fetchone()[0]
            items=[enrich(db,kind,dict(x)) for x in db.execute(f'SELECT * FROM {kind}'+where+' ORDER BY created_at DESC,id DESC LIMIT 25 OFFSET ?',[*args,(page-1)*25])]
        return {'items':[visible(user,kind,x) for x in items],'total':total,'page':page,'page_size':25}

    @r.get('/{kind}/{identifier}')
    def detail(kind:str,identifier:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            item=enrich(db,kind,row(db,kind,identifier))
            if kind=='clients':item['enquiries']=[dict(x) for x in db.execute('SELECT e.id,e.reference,e.service,e.status,e.created_at FROM enquiries e JOIN enquiry_clients l ON l.enquiry_id=e.id WHERE l.client_id=? ORDER BY e.created_at DESC',(identifier,))]
            audit(db,user['staff_id'],'view_'+kind,item['reference'])
            return visible(user,kind,item)

    @r.post('/{kind}',status_code=201)
    def create(kind:str,data:dict,user=Depends(staff)):
        kind_table(kind);v=values(kind,data)
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');links(db,kind,v)
            return insert(db,kind,v,user)

    @r.put('/{kind}/{identifier}')
    def update(kind:str,identifier:str,data:dict,user=Depends(staff)):
        kind_table(kind);v=values(kind,data)
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');previous=row(db,kind,identifier);links(db,kind,v,identifier)
            v['updated_at']=now()
            db.execute(f"UPDATE {kind} SET "+','.join(k+'=?' for k in v)+' WHERE id=?',[*v.values(),identifier])
            history(db,user['staff_id'],kind,identifier,previous,row(db,kind,identifier))
            audit(db,user['staff_id'],'update_'+kind,previous['reference'])
            return enrich(db,kind,row(db,kind,identifier))

    @r.delete('/{kind}/{identifier}')
    def delete(kind:str,identifier:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');previous=row(db,kind,identifier)
            if kind in {'quotes','invoices'}:
                db.execute('DELETE FROM pdf_artifacts WHERE copy_id IN (SELECT id FROM document_copies WHERE kind=? AND record_id=?)',(kind,identifier))
                db.execute("UPDATE document_copies SET revoked_at=COALESCE(revoked_at,?),snapshot_json='{}',checksum='' WHERE kind=? AND record_id=?",(now(),kind,identifier))
            try:db.execute(f'DELETE FROM {kind} WHERE id=?',(identifier,))
            except sqlite3.IntegrityError:raise HTTPException(409,'This record has linked records. Archive it or remove those links first.')
            history(db,user['staff_id'],kind,identifier,previous,None)
            audit(db,user['staff_id'],'delete_'+kind,previous['reference'])
        return {'ok':True}
    return r
