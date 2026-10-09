import base64
import hashlib
from app.db import connect, initialize
from test_backend import client, signin, record
from test_crm import create, profile

BASE='/api/admin/experience/'
PORTAL='/api/client/'

def setup(client):
    h=signin(client);a=profile(client,h);b=profile(client,h,'Another organization')
    return h,a,b

def invitation(client,h,cid,email='client@example.com'):
    r=client.post(BASE+'clients/'+cid+'/invite',json={'email':email},headers=h)
    assert r.status_code==201,r.text
    return r.json()['activation_url'].split('#invite=')[1]

def activate(client,token):
    r=client.post(PORTAL+'activate',json={'token':token,'password':'client-test-password'})
    assert r.status_code==200,r.text
    return {'X-CSRF-Token':r.json()['csrf']}

def publish(client,h,p):
    return client.put(BASE+'projects/'+p['id']+'/progress',json={'stage':'planning','summary':'Survey complete. Planning the network.','next_milestone':'Confirm equipment','waiting_on':'Approve room layout','target_date':'2026-12-01'},headers=h)

def shared_quote(client,h,cid,**changes):
    q=create(client,'quotes',dict(client_id=cid,title='Network setup',status='sent',amount_minor=10000,**changes),h)
    cp=client.post('/api/admin/documents/quotes/'+q['id']+'/copies',json={},headers=h)
    assert cp.status_code==201,cp.text
    copy=cp.json()
    r=client.post(BASE+'clients/'+cid+'/documents',json={'copy_id':copy['id']},headers=h)
    assert r.status_code==201,r.text
    return q,copy

def test_invites_sessions_csrf_isolation_revoke_and_password_reset(client):
    h,a,b=setup(client)
    t=invitation(client,h,a['id']);ch=activate(client,t)
    assert client.get(PORTAL+'me').json()['name']==a['name']
    assert client.post(PORTAL+'activate',json={'token':t,'password':'client-test-password'}).status_code==400
    assert client.post(PORTAL+'logout',json={}).status_code==403
    assert client.post('/api/admin/crm/clients',json={'name':'Intruder','email':'i@example.com'},headers=ch).status_code==403
    assert client.post(BASE+'clients/'+b['id']+'/invite',json={'email':'client@example.com'},headers=h).status_code==409
    assert 'password_hash' not in client.get(BASE+'clients/'+a['id']+'/access').text
    t2=invitation(client,h,a['id']);activate(client,t2)
    with connect(client.settings.db_path) as db:
        assert db.execute('SELECT count(*) FROM portal_sessions').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM portal_invites WHERE token_hash=?',(hashlib.sha256(t2.encode()).hexdigest(),)).fetchone()[0]==1
    assert client.post(PORTAL+'logout',json={},headers=ch).status_code==403  # old CSRF is invalid
    assert client.post(BASE+'clients/'+a['id']+'/revoke-access',json={},headers=h).status_code==200
    assert client.get(PORTAL+'me').status_code==401
    assert client.post(PORTAL+'login',json={'email':'client@example.com','password':'client-test-password'}).status_code==401
    expired=invitation(client,h,b['id'],'another@example.com')
    with connect(client.settings.db_path) as db:db.execute('UPDATE portal_invites SET expires=0')
    assert client.post(PORTAL+'activate',json={'token':expired,'password':'client-test-password'}).status_code==400

def test_progress_explicit_publication_and_private_notes(client):
    h,a,b=setup(client)
    p=create(client,'projects',dict(client_id=a['id'],title='Network',description='INTERNAL SECRET',status='active'),h)
    other=create(client,'projects',dict(client_id=b['id'],title='Other network'),h)
    assert publish(client,h,other).status_code==200
    activate(client,invitation(client,h,a['id']))
    assert client.get(PORTAL+'projects').json()['items']==[]
    assert publish(client,h,p).status_code==200
    view=client.get(PORTAL+'projects');assert 'INTERNAL SECRET' not in view.text and 'assigned_to' not in view.text
    assert [x['id'] for x in view.json()['items']]==[p['id']]
    assert client.put('/api/admin/crm/projects/'+p['id'],json=dict(client_id=b['id'],title='Network'),headers=h).status_code==409
    assert client.delete(BASE+'projects/'+p['id']+'/progress',headers=h).status_code==200
    assert client.get(PORTAL+'projects').json()['items']==[]
    assert client.get(PORTAL+'me').headers['referrer-policy']=='no-referrer'
    assert client.get('/client').headers['cache-control']=='no-store'

def test_document_approval_binds_current_copy_and_is_repeat_safe(client):
    h,a,b=setup(client);q,copy=shared_quote(client,h,a['id']);other,othercopy=shared_quote(client,h,b['id'])
    ch=activate(client,invitation(client,h,a['id']))
    data=client.get(PORTAL+'documents').json()['items'];assert len(data)==1 and data[0]['id']==copy['id']
    assert client.get(PORTAL+'documents/'+othercopy['id']+'/pdf').status_code==404
    assert client.post(PORTAL+'documents/'+othercopy['id']+'/decision',json={'action':'accept'},headers=ch).status_code==404
    pdf=client.get(PORTAL+'documents/'+copy['id']+'/pdf');assert hashlib.sha256(pdf.content).hexdigest()==copy['pdf_sha256']
    assert client.post(PORTAL+'documents/'+copy['id']+'/decision',json={'action':'request_changes'},headers=ch).status_code==422
    changed=client.post(PORTAL+'documents/'+copy['id']+'/decision',json={'action':'request_changes','message':'Please include training.'},headers=ch)
    assert changed.status_code==201
    accepted=client.post(PORTAL+'documents/'+copy['id']+'/decision',json={'action':'accept'},headers=ch)
    assert accepted.status_code==201 and accepted.json()['accepted_at']
    assert client.get('/api/admin/crm/quotes/'+q['id']).json()['status']=='accepted'
    assert client.post(PORTAL+'documents/'+copy['id']+'/decision',json={'action':'accept'},headers=ch).status_code==201
    with connect(client.settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM quote_decisions WHERE action='accept'").fetchone()[0]==1
        assert db.execute("SELECT checksum FROM quote_decisions WHERE action='accept'").fetchone()[0]==copy['fingerprint']
    assert client.post(PORTAL+'documents/'+copy['id']+'/decision',json={'action':'request_changes','message':'Another change'},headers=ch).status_code==409
    decisions=client.get(BASE+'decisions',params={'client_id':a['id']}).json()['items'];assert len(decisions)==2
    assert client.post('/api/admin/documents/copies/'+copy['id']+'/revoke',json={},headers=h).status_code==200
    assert client.get(PORTAL+'documents').json()['items']==[]
    assert client.get(PORTAL+'documents/'+copy['id']+'/pdf').status_code==404

def test_stale_expired_and_draft_documents_cannot_be_approved(client):
    h,a,b=setup(client);q,copy=shared_quote(client,h,a['id'])
    old,oldcopy=shared_quote(client,h,a['id'],due_date='2000-01-01')
    ch=activate(client,invitation(client,h,a['id']))
    assert client.post(PORTAL+'documents/'+oldcopy['id']+'/decision',json={'action':'accept'},headers=ch).status_code==409
    assert client.put('/api/admin/crm/quotes/'+q['id'],json=dict(client_id=a['id'],title=q['title'],status='sent',amount_minor=20000),headers=h).status_code==200
    assert client.post(PORTAL+'documents/'+copy['id']+'/decision',json={'action':'accept'},headers=ch).status_code==409
    draft=create(client,'quotes',dict(client_id=a['id'],title='Draft',amount_minor=500),h)
    cp=client.post('/api/admin/documents/quotes/'+draft['id']+'/copies',json={},headers=h).json()
    assert client.post(BASE+'clients/'+a['id']+'/documents',json={'copy_id':cp['id']},headers=h).status_code==409
    assert client.post(BASE+'clients/'+b['id']+'/documents',json={'copy_id':copy['id']},headers=h).status_code==404
    assert client.put('/api/admin/crm/quotes/'+q['id'],json=dict(client_id=b['id'],title=q['title'],status='sent',amount_minor=20000),headers=h).status_code==409

def test_support_conversations_keep_internal_description_private(client):
    h,a,b=setup(client)
    private=create(client,'tickets',dict(client_id=a['id'],title='Internal request',description='PRIVATE NOTES'),h)
    other=create(client,'tickets',dict(client_id=b['id'],title='Other organization'),h)
    ch=activate(client,invitation(client,h,a['id']))
    assert 'PRIVATE NOTES' not in client.get(PORTAL+'tickets').text
    req=client.post(PORTAL+'tickets',json={'title':'Network outage','description':'The upstairs connection is unavailable.'},headers=ch)
    assert req.status_code==201,req.text
    tid=req.json()['id'];path=PORTAL+'tickets/'+tid+'/messages'
    assert client.get(path).json()['items'][0]['author']=='client'
    assert client.post(BASE+'tickets/'+tid+'/messages',json={'text':'VICAM is checking the link.'},headers=h).status_code==201
    assert client.post(path,json={'text':'Thank you.'},headers=ch).status_code==201
    assert [x['author'] for x in client.get(path).json()['items']].count('VICAM')==1
    assert client.get(PORTAL+'tickets/'+other['id']+'/messages').status_code==404
    assert client.post(PORTAL+'tickets/'+other['id']+'/messages',json={'text':'Unauthorized'},headers=ch).status_code==404
    assert client.put('/api/admin/crm/tickets/'+tid,json=dict(client_id=b['id'],title='Network outage'),headers=h).status_code==409
    assert client.get(PORTAL+'tickets/'+private['id']+'/messages').json()['items']==[]

def test_files_validation_isolation_body_limit_quota_and_backup(client):
    h,a,b=setup(client)
    other=create(client,'projects',dict(client_id=b['id'],title='Other site'),h)
    ch=activate(client,invitation(client,h,a['id']))
    file={'name':'requirements.txt','content_base64':base64.b64encode(b'Project requirements').decode()}
    r=client.post(PORTAL+'files',json=file,headers=ch);assert r.status_code==201,r.text
    fid=r.json()['id'];download=client.get(PORTAL+'files/'+fid+'/download')
    assert download.content==b'Project requirements' and download.headers['content-type']=='application/octet-stream'
    assert 'attachment' in download.headers['content-disposition']
    assert client.post(PORTAL+'files',json=dict(file,project_id=other['id']),headers=ch).status_code==404
    for name in ['../../bad.txt','malware.exe','fake.pdf']:
        assert client.post(PORTAL+'files',json=dict(file,name=name),headers=ch).status_code==422
    large=dict(file,content_base64=base64.b64encode(b'x'*40000).decode())
    assert client.post(PORTAL+'files',json=large,headers=ch).status_code==201
    oversized=dict(file,content_base64=base64.b64encode(b'x'*(2*1024*1024+1)).decode())
    assert client.post(PORTAL+'files',json=oversized,headers=ch).status_code==413
    foreign=client.post(BASE+'clients/'+b['id']+'/files',json=file,headers=h).json()['id']
    assert client.get(PORTAL+'files/'+foreign+'/download').status_code==404
    assert client.get(PORTAL+'files').json()['items'][0]['name']=='requirements.txt'
    assert client.delete(BASE+'files/'+fid,headers=h).status_code==200
    assert client.get(PORTAL+'files/'+fid+'/download').status_code==404
    initialize(client.settings.db_path)  # repeat startup must preserve uploaded bytes
    assert client.get(PORTAL+'files').json()['items'][0]['size']==40000

def test_followups_correct_balances_dates_cases_and_enquiry_context(client):
    h,a,b=setup(client);enq=record(client)
    with connect(client.settings.db_path) as db:db.execute("UPDATE enquiries SET created_at='2000-01-01' WHERE id=?",(enq['id'],))
    create(client,'tasks',dict(client_id=a['id'],title='Call client',due_date='2000-01-01'),h)
    create(client,'quotes',dict(client_id=a['id'],title='Sent quote',status='sent',amount_minor=100,due_date='2000-01-01'),h)
    i=create(client,'invoices',dict(client_id=a['id'],title='Overdue invoice',status='issued',amount_minor=100,due_date='2000-01-01'),h)
    create(client,'payments',dict(invoice_id=i['id'],amount_minor=40,paid_date='2026-01-01',external_reference='PARTIAL'),h)
    create(client,'contracts',dict(client_id=a['id'],title='Renewal',status='active',start_date='2000-01-01',end_date='2001-01-01'),h)
    x=client.get(BASE+'follow-ups').json()['items'];assert {r['kind'] for r in x}=={'enquiry','task','quotation','invoice','contract'}
    assert next(r for r in x if r['kind']=='invoice')['balance_minor']==60
    create(client,'payments',dict(invoice_id=i['id'],amount_minor=60,paid_date='2026-01-01',external_reference='FINAL'),h)
    assert 'invoice' not in {r['kind'] for r in client.get(BASE+'follow-ups').json()['items']}
    case=dict(title='Approved network project',service='IT support',problem='Connectivity interrupted daily work.',solution='The team improved the network layout.',result='Staff confirmed stable connectivity.',published=True,permission_confirmed=False)
    assert client.post(BASE+'case-studies',json=case,headers=h).status_code==422
    case['permission_confirmed']=True
    cid=client.post(BASE+'case-studies',json=case,headers=h).json()['id']
    assert len(client.get('/api/public/case-studies').json()['items'])==1
    case['published']=False
    assert client.put(BASE+'case-studies/'+cid,json=case,headers=h).status_code==200
    assert client.get('/api/public/case-studies').json()['items']==[]
    assert client.delete(BASE+'case-studies/'+cid,headers=h).status_code==200
    assert client.get('/api/public/case-studies').json()['items']==[]

def test_every_new_staff_route_requires_signin_and_portal_not_staff(client):
    for path in ['follow-ups','case-studies','clients/unknown/access','clients/unknown/files','projects/unknown/progress','tickets/unknown/messages','decisions?client_id=unknown']:
        assert client.get(BASE+path).status_code==401
    for path in ['me','projects','documents','tickets','files','files/unknown/download']:
        assert client.get(PORTAL+path).status_code==401
    h,a,b=setup(client);activate(client,invitation(client,h,a['id']))
    # A client cookie alone never grants access to the staff workspace.
    client.cookies.delete('vicam_session')
    assert client.get(BASE+'follow-ups').status_code==401
    assert client.get('/api/admin/crm/clients').status_code==401
    assert client.post(PORTAL+'tickets',json={'title':'Help','description':'A valid support request'}).status_code==403
    assert client.post(PORTAL+'login',json={'email':'client@example.com','password':'client-test-password'},headers={'Origin':'https://attacker.example'}).status_code==403


def test_schema_four_upgrade_preserves_artifacts_payments_and_accounts(client):
    h,a,b=setup(client);q,copy=shared_quote(client,h,a['id'])
    activate(client,invitation(client,h,a['id']))
    with connect(client.settings.db_path) as db:
        # Remove only new tables/column, representing a schema-4 installation.
        for table in ['client_files','ticket_messages','quote_decisions','portal_documents','project_progress','portal_sessions','portal_invites','portal_accounts','case_studies']:
            db.execute('DROP TABLE '+table)
        db.execute('ALTER TABLE enquiries DROP COLUMN service_context')
        db.execute('PRAGMA user_version=4')
        original=db.execute('SELECT pdf_bytes FROM pdf_artifacts WHERE copy_id=?',(copy['id'],)).fetchone()[0]
    initialize(client.settings.db_path);initialize(client.settings.db_path)
    with connect(client.settings.db_path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==8
        assert db.execute('SELECT pdf_bytes FROM pdf_artifacts WHERE copy_id=?',(copy['id'],)).fetchone()[0]==original
        assert db.execute('SELECT count(*) FROM clients').fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM portal_accounts').fetchone()[0]==0
        assert db.execute('SELECT can_issue_docs FROM staff').fetchone()[0]==1
    assert client.get('/api/admin/crm/quotes/'+q['id']).status_code==200


def test_service_context_is_optional_durable_and_limited(client):
    from test_backend import payload
    data=payload();data['service_context']='Devices: 20\nCurrent tools: Office suite'
    assert client.post('/api/enquiries',json=data).status_code==201
    h=signin(client)
    identifier=client.get('/api/admin/enquiries').json()['items'][0]['id']
    assert client.get('/api/admin/enquiries/'+identifier).json()['service_context']==data['service_context']
    data['service_context']='x'*1001
    assert client.post('/api/enquiries',json=data).status_code==422
