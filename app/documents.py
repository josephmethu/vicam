"""Server-backed document verification. A QR identifies an immutable saved copy."""
import base64
import hashlib
import io
import json
import re
import secrets
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from qrcode import QRCode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.svg import SvgPathImage
from .pdf_documents import generate_pdf
from .config import ROOT
from .pricing import terms
from .db import audit, connect, now
from .security import rate_limit, token_hash

SCHEMA = '''
CREATE TABLE IF NOT EXISTS document_copies(
 id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('quotes','invoices')), record_id TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, checksum TEXT NOT NULL, created_at TEXT NOT NULL,
 staff_id INTEGER NOT NULL REFERENCES staff(id), revoked_at TEXT);
CREATE INDEX IF NOT EXISTS copies_record ON document_copies(kind,record_id,created_at);
'''

def canonical(snapshot):
    return json.dumps(snapshot,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def checksum(snapshot):
    return hashlib.sha256(canonical(snapshot).encode()).hexdigest()

def snapshot(db,kind,identifier,settings=None):
    if kind not in {'quotes','invoices'}:raise HTTPException(404,'Only quotations and invoices have verification copies')
    item=db.execute(f'SELECT * FROM {kind} WHERE id=?',(identifier,)).fetchone()
    if not item:raise HTTPException(404,'Document not found')
    client=db.execute('SELECT name,organization FROM clients WHERE id=?',(item['client_id'],)).fetchone()
    copy={'kind':kind,'reference':item['reference'],'client_name':client['name'],'organization':client['organization'],
          'title':item['title'],'description':item['description'],'status':item['status'],
          'amount_minor':item['amount_minor'],'currency':item['currency'],'due_date':item['due_date']}
    if item['pricing_json']:copy['pricing']=json.loads(item['pricing_json'])
    if kind=='invoices':
        paid=db.execute('SELECT COALESCE(sum(amount_minor),0) FROM payments WHERE invoice_id=?',(identifier,)).fetchone()[0]
        copy.update(paid_minor=paid,balance_minor=item['amount_minor']-paid)
    if settings and (settings.business_name!="VICAM" or settings.business_registration or settings.company_email):
        copy["issuer"]={"name":settings.business_name,"registration":settings.business_registration,"email":settings.company_email}
    return copy

def qr_data(url):
    code=QRCode(error_correction=ERROR_CORRECT_M,box_size=10,border=4)
    code.add_data(url);code.make(fit=True)
    buffer=io.BytesIO();code.make_image(image_factory=SvgPathImage).save(buffer)
    return 'data:image/svg+xml;base64,'+base64.b64encode(buffer.getvalue()).decode()

def routers(settings,staff):
    private=APIRouter(prefix='/api/admin/documents',dependencies=[Depends(staff)])
    public=APIRouter()

    def require_issuer(user):
        if not user['can_issue_docs']:raise HTTPException(403,'Document issuing permission is required')

    def issue_copy(kind,identifier,user,signed=False):
        require_issuer(user)
        if signed and settings.pdf_signing_mode=='disabled':raise HTTPException(409,'Configure a signing certificate before issuing signed PDFs')
        token=secrets.token_urlsafe(32);copy_id=uuid.uuid4().hex;stamp=now()
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            original=snapshot(db,kind,identifier,settings)
            if kind=='invoices' and original['status']=='void':raise HTTPException(409,'A void invoice cannot receive a new verification copy')
            if signed and original['status'] not in ({'sent','accepted'} if kind=='quotes' else {'issued'}):raise HTTPException(409,'Set the quotation to sent/accepted or invoice to issued before signing')
            url=settings.origin+'/verify/#'+token
            try:pdf,digest,mode,certificate=generate_pdf(original,copy_id,stamp,url,settings,signed)
            except Exception as exc:raise HTTPException(409,'PDF generation or signing failed; no document was issued') from exc
            db.execute('INSERT INTO document_copies VALUES(?,?,?,?,?,?,?,?,NULL)',
                (copy_id,token_hash(token),kind,identifier,canonical(original),checksum(original),stamp,user['staff_id']))
            db.execute('INSERT INTO pdf_artifacts VALUES(?,?,?,?,?,?)',(copy_id,pdf,digest,mode,certificate,stamp))
            audit(db,user['staff_id'],'issue_document_copy',original['reference'])
        # The unpredictable URL acts as a bearer link for the document's recipient.
        url=settings.origin+'/verify/#'+token
        return {'id':copy_id,'issued_at':stamp,'snapshot':original,'fingerprint':checksum(original),
                'download_url':'/api/admin/documents/copies/'+copy_id+'/pdf','pdf_sha256':digest,'signing_mode':mode,'certificate_sha256':certificate,
                'verification_url':url,'qr_data_uri':qr_data(url),'local_only':not settings.production}

    @private.post('/{kind}/{identifier}/copies',status_code=201)
    def issue(kind:str,identifier:str,user=Depends(staff)):
        return issue_copy(kind,identifier,user)

    @private.post('/{kind}/{identifier}/signed-pdf',status_code=201)
    def signed_pdf(kind:str,identifier:str,user=Depends(staff)):
        return issue_copy(kind,identifier,user,True)

    def pdf_response(item):
        if not item or hashlib.sha256(item['pdf_bytes']).hexdigest()!=item['pdf_sha256']:raise HTTPException(409,'Original PDF unavailable or damaged')
        return Response(item['pdf_bytes'],media_type='application/pdf',headers={'Content-Disposition':'attachment; filename=VICAM-'+item['copy_id'][:8]+'.pdf','Cache-Control':'no-store'})

    @private.get('/copies/{copy_id}/pdf')
    def download(copy_id:str):
        with connect(settings.db_path) as db:
            return pdf_response(db.execute('SELECT * FROM pdf_artifacts WHERE copy_id=?',(copy_id,)).fetchone())

    @private.get('/{kind}/{identifier}/copies')
    def copies(kind:str,identifier:str):
        with connect(settings.db_path) as db:
            snapshot(db,kind,identifier,settings)
            items=[dict(x) for x in db.execute('SELECT c.id,c.created_at,c.revoked_at,c.checksum,p.pdf_sha256,p.signing_mode FROM document_copies c LEFT JOIN pdf_artifacts p ON p.copy_id=c.id WHERE kind=? AND record_id=? ORDER BY c.created_at DESC,c.id DESC',(kind,identifier))]
        return {'items':items}

    @private.post('/copies/{copy_id}/revoke')
    def revoke(copy_id:str,user=Depends(staff)):
        require_issuer(user)
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            item=db.execute('SELECT * FROM document_copies WHERE id=?',(copy_id,)).fetchone()
            if not item:raise HTTPException(404,'Verification copy not found')
            db.execute('UPDATE document_copies SET revoked_at=COALESCE(revoked_at,?) WHERE id=?',(now(),copy_id))
            audit(db,user['staff_id'],'withdraw_document_copy',copy_id)
        return {'ok':True}

    @public.get('/verify/')
    def verify_page():
        return FileResponse(ROOT/'static/verify.html')

    @public.get('/api/verify/{token}')
    def verify(token:str,request:Request):
        ip=request.client.host if request.client else 'unknown'
        rate_limit(settings.db_path,'verify',ip,120,3600)
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise HTTPException(404,'Verification code not found')
        with connect(settings.db_path) as db:
            item=db.execute('SELECT * FROM document_copies WHERE token_hash=?',(token_hash(token),)).fetchone()
            if not item:raise HTTPException(404,'Verification code not found')
            if item['revoked_at']:
                return {'state':'withdrawn','issued_at':item['created_at'],'message':'VICAM has withdrawn this verification copy. Ask for a current document.'}
            try:
                original=json.loads(item['snapshot_json'])
                if checksum(original)!=item['checksum']:raise ValueError()
            except (ValueError,TypeError):
                return {'state':'unavailable','message':'This record cannot be verified. Contact VICAM before relying on it.'}
            try:current=snapshot(db,item['kind'],item['record_id'],settings)
            except HTTPException:
                return {'state':'withdrawn','issued_at':item['created_at'],'message':'The source document was removed. Ask VICAM for a current document.'}
            if item['kind']=='invoices' and current['status']=='void':
                return {'state':'withdrawn','issued_at':item['created_at'],'message':'This invoice has been voided. Do not rely on this copy.'}
            artifact=db.execute('SELECT * FROM pdf_artifacts WHERE copy_id=?',(item['id'],)).fetchone()
            if artifact and hashlib.sha256(artifact['pdf_bytes']).hexdigest()!=artifact['pdf_sha256']:return {'state':'unavailable','message':'The stored PDF cannot be verified. Contact VICAM.'}
            pdf_info={} if not artifact else {'pdf_sha256':artifact['pdf_sha256'],'signing_mode':artifact['signing_mode'],'certificate_sha256':artifact['certificate_sha256'],'download_url':'/api/verify/'+token+'/pdf'}
            if not settings.verification_public_details:
                pdf_info.pop('download_url',None)
            live={'status':current['status'],'checked_at':now(),'source':'Business-recorded information; no bank or payment-provider confirmation'}
            if item['kind']=='invoices':
                live.update(paid_minor=current['paid_minor'],balance_minor=current['balance_minor'],currency=current['currency'])
                live['payment_status']='paid' if current['balance_minor']==0 else 'partially_paid' if current['paid_minor']>0 else 'unpaid'
            else:
                today=datetime.now(ZoneInfo(settings.business_timezone)).date().isoformat()
                live['expired']=bool(current['due_date'] and current['due_date']<today and current['status'] not in {'accepted','declined'})
            public_original=original if settings.verification_public_details else {k:v for k,v in original.items() if k not in {'client_name','organization','description','title'}}
            state='current' if checksum(terms(current))==checksum(terms(original)) else 'superseded'
            return {**pdf_info,'state':state,'issued_at':item['created_at'],'snapshot':public_original,'issuer':original.get('issuer',{'name':'VICAM'}),'live':live,'fingerprint':item['checksum'],
                    'record_changed':checksum(current)!=item['checksum'],'current_status':current['status'],'message':'The saved terms match the current document. Check live status separately.' if state=='current' else 'The document terms have changed since this copy was created. Ask the issuer for an updated copy.',
                    'local_only':not settings.production}
    @public.get('/api/verify/{token}/pdf')
    def public_pdf(token:str,request:Request):
        result=verify(token,request)
        if not settings.verification_public_details:raise HTTPException(403,'Download this document through the private client portal')
        if result['state'] not in {'current','superseded'}:raise HTTPException(410,'This copy is unavailable or withdrawn')
        with connect(settings.db_path) as db:
            return pdf_response(db.execute('SELECT p.* FROM pdf_artifacts p JOIN document_copies c ON c.id=p.copy_id WHERE c.token_hash=?',(token_hash(token),)).fetchone())

    return private,public
