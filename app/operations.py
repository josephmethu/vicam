"""Admin-only operations; backup verification and private record history."""
import asyncio
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime,timezone
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from .db import connect,now

SCHEMA='''
CREATE TABLE IF NOT EXISTS record_history(id INTEGER PRIMARY KEY,staff_id INTEGER REFERENCES staff(id),kind TEXT NOT NULL,record_id TEXT NOT NULL,before_json TEXT,after_json TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_record ON record_history(kind,record_id,id);
CREATE TABLE IF NOT EXISTS delivery_jobs(id TEXT PRIMARY KEY,dedupe_key TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,copy_id TEXT REFERENCES document_copies(id) ON DELETE CASCADE,recipient TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt INTEGER NOT NULL DEFAULT 0,lease_at INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
'''

def history(db,staff_id,kind,record_id,before,after):
    encode=lambda x:json.dumps(x,sort_keys=True,separators=(',',':')) if x is not None else None
    db.execute('INSERT INTO record_history(staff_id,kind,record_id,before_json,after_json,created_at) VALUES(?,?,?,?,?,?)',(staff_id,kind,record_id,encode(before),encode(after),now()))

def file_digest(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda:file.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest()

def verify_backup(path):
    path=Path(path);manifest=json.loads(path.with_suffix('.json').read_text())
    if file_digest(path)!=manifest['sha256']:raise ValueError('Backup fingerprint differs')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Backup database check failed')
        if db.execute('PRAGMA user_version').fetchone()[0]!=manifest['schema']:raise ValueError('Backup schema differs')
    return manifest

def make_backup(settings):
    if not settings.backup_directory:raise ValueError('Configure BACKUP_DIRECTORY')
    folder=Path(settings.backup_directory);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    stem='vicam-auto-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    target=folder/(stem+'.sqlite3');temp=folder/(stem+'.partial')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    try:
        with sqlite3.connect(settings.db_path) as src,sqlite3.connect(temp) as dst:src.backup(dst)
        with sqlite3.connect(temp) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Backup check failed')
            schema=db.execute('PRAGMA user_version').fetchone()[0]
        manifest={'created_at':now(),'sha256':file_digest(temp),'schema':schema}
        os.replace(temp,target)
        fd=os.open(target.with_suffix('.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as file:json.dump(manifest,file)
        verify_backup(target)
        files=sorted(folder.glob('vicam-auto-*.sqlite3'),key=lambda p:p.name,reverse=True)
        for old in files[settings.backup_keep:]:
            # Only prune backups created by this tool with a valid paired manifest.
            try:verify_backup(old)
            except Exception:continue
            old.unlink();old.with_suffix('.json').unlink()
        return target
    finally:
        temp.unlink(missing_ok=True)

async def backup_worker(settings):
    import logging
    while True:
        try:await asyncio.to_thread(make_backup,settings)
        except Exception:logging.getLogger('vicam.backups').error('Automatic backup failed; check private storage and backup status')
        await asyncio.sleep(settings.backup_interval_hours*3600)

def router(settings,staff):
    r=APIRouter(prefix='/api/admin/operations',dependencies=[Depends(staff)])
    @r.get('/status')
    def status():
        with connect(settings.db_path) as db:
            checks=db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            jobs=[dict(x) for x in db.execute('SELECT state,count(*) AS count FROM delivery_jobs GROUP BY state')]
            enquiries=[dict(x) for x in db.execute('SELECT state,count(*) AS count FROM outbox GROUP BY state')]
        latest=None
        if settings.backup_directory:
            files=sorted(Path(settings.backup_directory).glob('vicam-auto-*.sqlite3'),reverse=True)
            if files:
                try:latest={**verify_backup(files[0]),'verified':True}
                except Exception:latest={'verified':False}
        return {'database_ok':checks,'email_configured':settings.email_ready,'backup_enabled':bool(settings.backup_directory),'latest_backup':latest,'delivery_jobs':jobs,'enquiry_notifications':enquiries,'signing_mode':settings.pdf_signing_mode}
    @r.get('/history/{kind}/{identifier}')
    def record_history(kind:str,identifier:str):
        with connect(settings.db_path) as db:
            rows=[dict(x) for x in db.execute('SELECT * FROM record_history WHERE kind=? AND record_id=? ORDER BY id DESC LIMIT 200',(kind,identifier))]
        for x in rows:
            x['before']=json.loads(x.pop('before_json')) if x['before_json'] else None
            x['after']=json.loads(x.pop('after_json')) if x['after_json'] else None
        return {'items':rows,'limit':200}
    @r.get('/clients/{cid}/export')
    def export(cid:str,user=Depends(staff)):
        from .db import audit
        with connect(settings.db_path) as db:
            c=db.execute('SELECT * FROM clients WHERE id=?',(cid,)).fetchone()
            if not c:raise HTTPException(404,'Client not found')
            result={'exported_at':now(),'client':dict(c)}
            for table in ('projects','tasks','quotes','invoices','tickets','contracts','client_files'):
                columns='id,client_id,project_id,name,mime,sha256,uploaded_by,created_at' if table=='client_files' else '*'
                result[table]=[dict(x) for x in db.execute(f'SELECT {columns} FROM {table} WHERE client_id=?',(cid,))]
            result['payments']=[dict(x) for x in db.execute('SELECT * FROM payments WHERE invoice_id IN (SELECT id FROM invoices WHERE client_id=?)',(cid,))]
            result['document_copies']=[dict(x) for x in db.execute("SELECT c.id,c.kind,c.record_id,c.created_at,c.revoked_at,c.checksum,p.pdf_sha256 FROM document_copies c LEFT JOIN pdf_artifacts p ON p.copy_id=c.id WHERE (c.kind='quotes' AND c.record_id IN (SELECT id FROM quotes WHERE client_id=?)) OR (c.kind='invoices' AND c.record_id IN (SELECT id FROM invoices WHERE client_id=?))",(cid,cid))]
            result['enquiries']=[dict(x) for x in db.execute('SELECT e.* FROM enquiries e JOIN enquiry_clients l ON l.enquiry_id=e.id WHERE l.client_id=?',(cid,))]
            result['note']='Private management export. Attachments and original PDFs are metadata only; download through their authenticated endpoints. Account credentials and verification bearer tokens are excluded.'
            audit(db,user['staff_id'],'export_client',cid)
        from fastapi.responses import JSONResponse
        return JSONResponse(result,headers={'Content-Disposition':'attachment; filename=VICAM-client-export.json'})
    return r
