import sqlite3
from datetime import date, timedelta
from pathlib import Path
import pytest
from test_backend import client, signin, record
from app.db import connect, initialize

BASE='/api/admin/crm/'
def create(client,kind,data,headers):
    r=client.post(BASE+kind,json=data,headers=headers)
    assert r.status_code==201,r.text
    return r.json()

def profile(client,headers,name='Example Client'):
    return create(client,'clients',{'name':name,'email':'client@example.com'},headers)

def issued(client,headers,cid,total=10000):
    return create(client,'invoices',dict(client_id=cid,title='Office support',status='issued',amount_minor=total),headers)

def payment(i,amount,ref='BANK-001'):
    return dict(invoice_id=i['id'],amount_minor=amount,paid_date='2026-10-02',method='bank_transfer',external_reference=ref)

def test_enquiry_conversion_is_explicit_and_repeat_safe(client):
    enq=record(client);h=signin(client)
    first=client.post(BASE+'convert/'+enq['id'],json={},headers=h)
    assert first.status_code==200
    cid=first.json()['id']
    assert client.post(BASE+'convert/'+enq['id'],json={},headers=h).json()['id']==cid
    detail=client.get(BASE+'clients/'+cid).json()
    assert detail['enquiries'][0]['reference']==enq['reference']
    other=profile(client,h,'Another Client')
    assert client.post(BASE+'convert/'+enq['id'],json={'client_id':other['id']},headers=h).status_code==409
    enq2=record(client)
    assert client.post(BASE+'convert/'+enq2['id'],json={'client_id':cid},headers=h).json()['id']==cid
    assert len(client.get(BASE+'clients/'+cid).json()['enquiries'])==2
    assert client.get(BASE+'clients').json()['total']==2
    assert client.delete(BASE+'clients/'+cid,headers=h).status_code==409
    assert client.delete('/api/admin/enquiries/'+enq['id'],headers=h).status_code==200
    assert client.get(BASE+'clients/'+cid).status_code==200

def test_all_linked_modules_edit_and_delete(client):
    h=signin(client);c=profile(client,h)
    staff=client.get(BASE+'staff').json()['items'][0]['id']
    p=create(client,'projects',dict(client_id=c['id'],title='Office network',assigned_to=staff,status='active'),h)
    entries={
      'tasks':dict(client_id=c['id'],project_id=p['id'],title='Call the client',due_date='2026-10-03',assigned_to=staff),
      'quotes':dict(client_id=c['id'],project_id=p['id'],title='Network quotation',amount_minor=12345),
      'invoices':dict(client_id=c['id'],project_id=p['id'],title='Network invoice',amount_minor=12345),
      'tickets':dict(client_id=c['id'],project_id=p['id'],title='Connection issue',priority='high',assigned_to=staff),
      'contracts':dict(client_id=c['id'],title='IT support agreement',start_date='2026-10-01',end_date='2027-10-01',assigned_to=staff)}
    for kind,data in entries.items():
        item=create(client,kind,data,h)
        changed=dict(data,title='Updated title')
        assert client.put(BASE+kind+'/'+item['id'],json=changed,headers=h).status_code==200
        assert client.get(BASE+kind+'/'+item['id']).json()['title']=='Updated title'
        assert client.delete(BASE+kind+'/'+item['id'],headers=h).status_code==200
    assert client.delete(BASE+'projects/'+p['id'],headers=h).status_code==200
    assert client.delete(BASE+'clients/'+c['id'],headers=h).status_code==200
    with connect(client.settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM audit WHERE action='update_tasks'").fetchone()[0]==1

def test_money_balances_constraints_and_currency(client):
    h=signin(client);c=profile(client,h);i=issued(client,h,c['id'])
    p=create(client,'payments',payment(i,4000),h)
    detail=client.get(BASE+'invoices/'+i['id']).json()
    assert (detail['paid_minor'],detail['balance_minor'],detail['payment_status'])==(4000,6000,'partial')
    assert client.post(BASE+'payments',json=payment(i,7000,'BANK-002'),headers=h).status_code==409
    assert client.post(BASE+'payments',json=payment(i,1000),headers=h).status_code==409
    original=dict(client_id=c['id'],title='Office support',status='issued',amount_minor=10000)
    for key,value in [('amount_minor',12000),('currency','USD'),('status','void')]:
        assert client.put(BASE+'invoices/'+i['id'],json=dict(original,**{key:value}),headers=h).status_code==409
    assert client.delete(BASE+'invoices/'+i['id'],headers=h).status_code==409
    assert client.put(BASE+'payments/'+p['id'],json=payment(i,3000),headers=h).status_code==200
    create(client,'payments',payment(i,7000,'BANK-002'),h)
    assert client.get(BASE+'invoices/'+i['id']).json()['payment_status']=='paid'
    assert client.delete(BASE+'payments/'+p['id'],headers=h).status_code==200
    assert client.get(BASE+'invoices/'+i['id']).json()['balance_minor']==3000
    draft=create(client,'invoices',dict(client_id=c['id'],title='Draft invoice',amount_minor=500),h)
    assert client.post(BASE+'payments',json=payment(draft,100),headers=h).status_code==409
    assert client.get(BASE+'payments',params={'invoice_id':i['id']}).json()['total']==1

def test_cross_client_and_staff_links(client):
    h=signin(client);a=profile(client,h);b=profile(client,h,'Second Client')
    p=create(client,'projects',dict(client_id=a['id'],title='Project'),h)
    task=dict(client_id=b['id'],project_id=p['id'],title='Task',due_date='2026-10-03')
    assert client.post(BASE+'tasks',json=task,headers=h).status_code==409
    task['client_id']=a['id'];t=create(client,'tasks',task,h)
    assert client.put(BASE+'projects/'+p['id'],json=dict(client_id=b['id'],title='Project'),headers=h).status_code==409
    assert client.delete(BASE+'projects/'+p['id'],headers=h).status_code==409
    assert client.post(BASE+'projects',json=dict(client_id=a['id'],title='Project',assigned_to=999),headers=h).status_code==409
    assert client.post(BASE+'projects',json=dict(client_id='missing',title='Project'),headers=h).status_code==404

def test_validation_and_no_dynamic_sql_injection(client):
    h=signin(client);c=profile(client,h)
    for v in [0,-1,1.5,True,'100',1000000000000]:
        assert client.post(BASE+'quotes',json=dict(client_id=c['id'],title='Quote',amount_minor=v),headers=h).status_code==422
    assert client.post(BASE+'clients',json={'name':'Hi','email':'invalid'},headers=h).status_code==422
    assert client.post(BASE+'contracts',json=dict(client_id=c['id'],title='Contract',start_date='2027-01-01',end_date='2026-01-01'),headers=h).status_code==422
    assert client.post(BASE+'tasks',json=dict(client_id=c['id'],title='Task',due_date='yesterday'),headers=h).status_code==422
    assert client.post(BASE+'clients',json={'name':'Valid','email':'c@example.com','staff_id':1},headers=h).status_code==422
    assert client.get(BASE+'clients',params={'q':"%' OR 1=1--"}).json()['total']==0
    assert client.get(BASE+'unknown').status_code==404
    assert client.post(BASE+'unknown',json={},headers=h).status_code==404
    assert client.get(BASE+'clients',params={'due_only':True}).status_code==422

def test_auth_csrf_every_module_and_private_page_headers(client):
    for kind in ['clients','projects','tasks','quotes','invoices','payments','tickets','contracts','summary','staff']:
        assert client.get(BASE+kind).status_code==401
    h=signin(client);c=profile(client,h)
    assert client.post(BASE+'clients',json={'name':'Test','email':'t@example.com'}).status_code==403
    assert client.put(BASE+'clients/'+c['id'],json={'name':'Changed','email':'t@example.com'}).status_code==403
    assert client.delete(BASE+'clients/'+c['id']).status_code==403
    page=client.get('/admin/clients')
    assert page.status_code==200 and 'unsafe-inline' not in page.headers['content-security-policy']
    assert page.headers['cache-control']=='no-store'
    assert 'password_hash' not in client.get(BASE+'staff').text

def test_due_reminders_client_search_pagination_and_archiving(client):
    h=signin(client);c=profile(client,h)
    for when,status in [('2000-01-01','open'),('2000-01-01','done'),('2099-01-01','open')]:
        create(client,'tasks',dict(client_id=c['id'],title='Reminder',due_date=when,status=status),h)
    due=client.get(BASE+'tasks',params={'due_only':True}).json()
    assert due['total']==1 and due['items'][0]['overdue'] is True
    assert client.get(BASE+'summary').json()['due_tasks']==1
    for n in range(26):profile(client,h,f'Client {n}')
    assert client.get(BASE+'clients').json()['total']==27
    assert len(client.get(BASE+'clients',params={'page':2}).json()['items'])==2
    assert client.get(BASE+'tasks',params={'client_id':c['id']}).json()['total']==3
    assert client.put(BASE+'clients/'+c['id'],json={'name':c['name'],'email':c['email'],'status':'archived'},headers=h).status_code==200
    assert client.get(BASE+'summary').json()['clients']==26
    assert client.get(BASE+'tasks',params={'client_id':c['id']}).json()['total']==3

def test_additive_migration_preserves_v1_data_and_is_repeatable(tmp_path):
    p=tmp_path/'old.sqlite3'
    # Original packaged v1 schema, before CRM tables existed.
    source=(Path(__file__).parent.parent/'app/db.py').read_text().split("db.executescript('''",1)[1].split("''')",1)[0]
    with sqlite3.connect(p) as db:
        db.executescript(source);db.execute('PRAGMA user_version=1')
        db.execute("INSERT INTO staff(email,password_hash) VALUES('old@example.com','stored-hash')")
        db.execute("INSERT INTO enquiries VALUES('old','VIC-OLD','stamp','stamp','Old Client','client@example.com','Software Development','Original brief','','','','','','','new','stamp','v1')")
    initialize(p);initialize(p)
    with connect(p) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==8
        assert db.execute('SELECT requirements FROM enquiries').fetchone()[0]=='Original brief'
        assert db.execute('SELECT password_hash FROM staff').fetchone()[0]=='stored-hash'
        assert db.execute('SELECT count(*) FROM clients').fetchone()[0]==0
        db.execute('PRAGMA user_version=9')
    with pytest.raises(RuntimeError):initialize(p)
