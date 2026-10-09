from app.db import connect, initialize
from test_backend import client, signin
from test_crm import profile, create
from test_experience import invitation, activate

BASE='/api/admin/experience/'
def equip(c,h,cid,**kw):
    r=c.post(BASE+'equipment',headers=h,json=dict(client_id=cid,name='Entrance camera',category='camera',notes='PRIVATE TECH NOTE',**kw));assert r.status_code==201,r.text;return r.json()
def report(c,h,cid,**kw):
    r=c.post(BASE+'reports',headers=h,json=dict(client_id=cid,visit_date='2026-10-08',technician='VICAM team',work_done='Installed and tested the entrance camera.',**kw));assert r.status_code==201,r.text;return r.json()
def test_equipment_publication_isolation_dates_and_role_permissions(client):
    h=signin(client);a=profile(client,h);b=profile(client,h,'Other client');p=create(client,'projects',dict(client_id=b['id'],title='Other project'),h)
    assert client.post(BASE+'equipment',headers=h,json=dict(client_id=a['id'],name='Wrong project',project_id=p['id'])).status_code==409
    assert client.post(BASE+'equipment',headers=h,json=dict(client_id=a['id'],name='Bad dates',installed_on='2026-10-10',warranty_until='2026-10-09')).status_code==422
    private=equip(client,h,a['id']);public=equip(client,h,a['id'],shared=True);equip(client,h,b['id'],shared=True)
    ch=activate(client,invitation(client,h,a['id']));r=client.get('/api/client/equipment');assert [x['id'] for x in r.json()['items']]==[public['id']];assert 'PRIVATE TECH NOTE' not in r.text and 'notes' not in r.text
    assert client.post(BASE+'equipment',headers=ch,json=dict(client_id=a['id'],name='Intrusion')).status_code==403
    with connect(client.settings.db_path) as db:db.execute("UPDATE staff SET role='finance'")
    assert client.get(BASE+'clients/'+a['id']+'/equipment').status_code==403
    with connect(client.settings.db_path) as db:db.execute("UPDATE staff SET role='support'")
    assert client.get(BASE+'clients/'+a['id']+'/equipment').status_code==200
    assert client.delete(BASE+'equipment/'+private['id'],headers=h).status_code==405

def test_reports_locked_explicit_acknowledgement_isolation_and_audit(client):
    h=signin(client);a=profile(client,h);b=profile(client,h,'Other client');asset=equip(client,h,a['id']);r=report(client,h,a['id'],equipment_id=asset['id']);other=report(client,h,b['id'])
    ch=activate(client,invitation(client,h,a['id']));assert client.get('/api/client/reports').json()['items']==[]
    assert client.post('/api/client/reports/'+r['id']+'/acknowledge',json={'confirmed':True},headers=ch).status_code==404
    shared=client.post(BASE+'reports/'+r['id']+'/share',json={},headers=h);assert shared.status_code==200;assert len(shared.json()['content_hash'])==64
    client.post(BASE+'reports/'+other['id']+'/share',json={},headers=h)
    assert client.post('/api/client/reports/'+other['id']+'/acknowledge',json={'confirmed':True},headers=ch).status_code==404
    view=client.get('/api/client/reports');assert len(view.json()['items'])==1;assert 'created_by' not in view.text
    assert client.put(BASE+'reports/'+r['id'],headers=h,json=dict(client_id=a['id'],visit_date='2026-10-08',technician='VICAM team',work_done='Changed work description')).status_code==409
    assert client.post('/api/client/reports/'+r['id']+'/acknowledge',json={'confirmed':True}).status_code==403
    assert client.post('/api/client/reports/'+r['id']+'/acknowledge',json={'confirmed':False},headers=ch).status_code==422
    ack=client.post('/api/client/reports/'+r['id']+'/acknowledge',json={'confirmed':True,'note':'Reviewed at handover'},headers=ch);assert ack.status_code==200;assert ack.json()['acknowledged_at']
    assert client.get(BASE+'clients/'+a['id']+'/reports').json()['items'][0]['acknowledged_email']=='client@example.com'
    retry=client.post('/api/client/reports/'+r['id']+'/acknowledge',json={'confirmed':True,'note':'Replaced'},headers=ch);assert retry.json()['acknowledgement_note']=='Reviewed at handover'
    with connect(client.settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM audit WHERE action='acknowledge_service_report'").fetchone()[0]==1
        assert db.execute('SELECT acknowledged_by FROM service_reports WHERE id=?',(r['id'],)).fetchone()[0]

def test_care_links_timeline_dashboard_and_preserved_project_ownership(client):
    h=signin(client);a=profile(client,h);b=profile(client,h,'Other client');p=create(client,'projects',dict(client_id=a['id'],title='Camera installation'),h)
    asset=equip(client,h,a['id'],project_id=p['id'],warranty_until='2099-01-01');r=report(client,h,a['id'],project_id=p['id'],equipment_id=asset['id']);client.post(BASE+'reports/'+r['id']+'/share',json={},headers=h)
    assert client.put('/api/admin/crm/projects/'+p['id'],headers=h,json=dict(client_id=b['id'],title='Moved project')).status_code==409
    assert client.put(BASE+'equipment/'+asset['id'],headers=h,json=dict(client_id=b['id'],name='Moved camera')).status_code==409
    assert client.delete('/api/admin/crm/clients/'+a['id'],headers=h).status_code==409
    q=create(client,'quotes',dict(client_id=a['id'],title='Equipment quotation',amount_minor=10000),h)
    t=client.get(BASE+'clients/'+a['id']+'/timeline');assert t.status_code==200;assert {'projects','equipment','service_reports','quotes'}<={x['kind'] for x in t.json()['items']}
    create(client,'invoices',dict(client_id=a['id'],title='KES invoice',status='issued',amount_minor=10000,currency='KES'),h)
    create(client,'invoices',dict(client_id=a['id'],title='USD invoice',status='issued',amount_minor=20000,currency='USD'),h)
    dash=client.get(BASE+'service-dashboard').json();assert dash['unacknowledged_reports']==1
    assert {x['currency']:x['amount_minor'] for x in dash['outstanding_by_currency']}=={'KES':10000,'USD':20000}
    with connect(client.settings.db_path) as db:db.execute("UPDATE staff SET role='support'")
    t=client.get(BASE+'clients/'+a['id']+'/timeline');assert 'quotes' not in [x['kind'] for x in t.json()['items']]
    assert 'outstanding_by_currency' not in client.get(BASE+'service-dashboard').json()
    assert client.get(BASE+'clients/'+a['id']+'/timeline?page=0').status_code==422

def test_additive_migration_retains_old_data(client):
    h=signin(client);a=profile(client,h)
    with connect(client.settings.db_path) as db:
        db.execute('DROP TABLE service_reports');db.execute('DROP TABLE equipment');db.execute('PRAGMA user_version=6')
    initialize(client.settings.db_path);initialize(client.settings.db_path)
    assert client.get('/api/admin/crm/clients/'+a['id']).json()['name']==a['name']
    assert client.get(BASE+'clients/'+a['id']+'/equipment').json()['items']==[]
