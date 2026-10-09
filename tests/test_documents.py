import base64
import hashlib
import json
from urllib.parse import urlsplit
from test_backend import client,signin
from test_crm import create,profile,issued,BASE,payment
from app.db import connect
from app.documents import checksum

DOC='/api/admin/documents/'
def copy(client,kind,item,h):
    r=client.post(DOC+kind+'/'+item['id']+'/copies',json={},headers=h)
    assert r.status_code==201,r.text
    return r.json()
def verify(client,issued):return client.get('/api/verify/'+urlsplit(issued['verification_url']).fragment)

def test_issue_qr_verify_private_data_and_headers(client):
    h=signin(client);c=profile(client,h);q=create(client,'quotes',dict(client_id=c['id'],title='Office support',description='Support office computers.',amount_minor=12345),h)
    result=copy(client,'quotes',q,h)
    token=urlsplit(result['verification_url']).fragment
    assert len(token)==43 and result['fingerprint']==checksum(result['snapshot'])
    svg=base64.b64decode(result['qr_data_uri'].split(',')[1]);assert b'<svg' in svg
    assert verify(client,result).json()['state']=='current'
    assert 'client@example.com' not in verify(client,result).text
    assert 'password' not in verify(client,result).text
    with connect(client.settings.db_path) as db:
        item=dict(db.execute('SELECT * FROM document_copies').fetchone())
        assert token not in json.dumps(item) and item['token_hash']==hashlib.sha256(token.encode()).hexdigest()
    assert client.get('/verify/').headers['referrer-policy']=='no-referrer'
    assert verify(client,result).headers['cache-control']=='no-store'
    assert verify(client,result).headers['x-robots-tag']=='noindex, nofollow'
    assert client.get('/api/verify/not-a-code').status_code==404
    assert client.get('/api/verify/'+'A'*43).status_code==404

def test_edited_copies_stay_immutable_and_new_versions_verify(client):
    h=signin(client);c=profile(client,h);data=dict(client_id=c['id'],title='Office support',amount_minor=10000)
    q=create(client,'quotes',data,h);old=copy(client,'quotes',q,h)
    assert client.put(BASE+'quotes/'+q['id'],json=dict(data,amount_minor=20000),headers=h).status_code==200
    state=verify(client,old).json()
    assert state['state']=='superseded' and state['snapshot']['amount_minor']==10000
    new=copy(client,'quotes',q,h)
    assert verify(client,new).json()['snapshot']['amount_minor']==20000
    assert old['verification_url']!=new['verification_url']
    assert client.get(DOC+'quotes/'+q['id']+'/copies').json()['items'][0]['id'] in {old['id'],new['id']}
    assert client.post(DOC+'copies/'+new['id']+'/revoke',json={},headers=h).status_code==200
    assert verify(client,new).json()['state']=='withdrawn' and 'snapshot' not in verify(client,new).json()
    assert client.post(DOC+'copies/'+new['id']+'/revoke',json={},headers=h).status_code==200
    assert client.delete(BASE+'quotes/'+q['id'],headers=h).status_code==200
    assert verify(client,old).json()['state']=='withdrawn'
    with connect(client.settings.db_path) as db:
        assert all(x[0]=='{}' for x in db.execute('SELECT snapshot_json FROM document_copies WHERE record_id=?',(q['id'],)))

def test_client_updates_balances_voiding_and_integrity_failure(client):
    h=signin(client);c=profile(client,h);i=issued(client,h,c['id']);old=copy(client,'invoices',i,h)
    create(client,'payments',payment(i,5000),h)
    assert verify(client,old).json()['state']=='current'
    assert verify(client,old).json()['record_changed'] is True
    fresh=copy(client,'invoices',i,h)
    assert verify(client,fresh).json()['snapshot']['balance_minor']==5000
    with connect(client.settings.db_path) as db:db.execute('UPDATE clients SET name=? WHERE id=?',('Changed name',c['id']))
    assert verify(client,fresh).json()['state']=='superseded'
    with connect(client.settings.db_path) as db:db.execute('UPDATE document_copies SET snapshot_json=? WHERE id=?',('{}',fresh['id']))
    assert verify(client,fresh).json()['state']=='unavailable'
    with connect(client.settings.db_path) as db:db.execute("UPDATE invoices SET status='void' WHERE id=?",(i['id'],))
    assert verify(client,old).json()['state']=='withdrawn'
    assert client.post(DOC+'invoices/'+i['id']+'/copies',json={},headers=h).status_code==409

def test_auth_csrf_and_unknown_types(client):
    assert client.get(DOC+'quotes/missing/copies').status_code==401
    assert client.post(DOC+'quotes/missing/copies',json={}).status_code==401
    h=signin(client);c=profile(client,h);q=create(client,'quotes',dict(client_id=c['id'],title='Office support',amount_minor=10000),h)
    assert client.post(DOC+'quotes/'+q['id']+'/copies',json={}).status_code==403
    assert client.post(DOC+'clients/'+c['id']+'/copies',json={},headers=h).status_code==404
    issued_copy=copy(client,'quotes',q,h)
    assert client.post(DOC+'copies/'+issued_copy['id']+'/revoke',json={}).status_code==403
    assert client.post(DOC+'copies/missing/revoke',json={},headers=h).status_code==404
    # Verification is intentionally available to the QR holder without a staff session.
    client.cookies.clear()
    assert verify(client,issued_copy).json()['state']=='current'
