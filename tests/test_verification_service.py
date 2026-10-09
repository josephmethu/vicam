from dataclasses import replace
from fastapi.testclient import TestClient
from test_backend import client,signin
from test_crm import create,profile,issued,payment
from test_documents import copy,verify
from app.main import create_app
from app.config import Settings

def test_live_payment_keeps_issued_snapshot(client):
    h=signin(client);c=profile(client,h);invoice=issued(client,h,c['id'])
    original=copy(client,'invoices',invoice,h)
    create(client,'payments',payment(invoice,3000),h)
    result=verify(client,original).json()
    assert result['snapshot']['paid_minor']==0
    assert result['live']['paid_minor']==3000 and result['live']['balance_minor']==7000
    assert result['live']['payment_status']=='partially_paid'
    assert 'no bank' in result['live']['source']
    assert result['pdf_sha256']==original['pdf_sha256']

def test_private_business_brand_and_expiry(client):
    settings=replace(client.settings,business_name='Example Engineering',business_registration='TEST-ONLY',verification_public_details=False)
    with TestClient(create_app(settings,enable_mail_worker=False)) as business:
        h=signin(business);c=profile(business,h)
        q=create(business,'quotes',dict(client_id=c['id'],title='Private project',description='Sensitive scope',status='sent',amount_minor=10000,due_date='2020-01-01'),h)
        original=copy(business,'quotes',q,h);result=verify(business,original).json()
        assert result['issuer']['name']=='Example Engineering'
        assert result['live']['expired'] is True and result['state']=='current'
        assert 'Sensitive scope' not in str(result) and 'client_name' not in result['snapshot']
        assert 'download_url' not in result
        token=original['verification_url'].split('#')[1]
        assert business.get('/api/verify/'+token+'/pdf').status_code==403
        assert business.get(original['download_url']).status_code==200

def test_separate_installation_cannot_resolve_other_business_token(client,tmp_path):
    h=signin(client);c=profile(client,h);q=create(client,'quotes',dict(client_id=c['id'],title='Project',amount_minor=100),h)
    original=copy(client,'quotes',q,h)
    with TestClient(create_app(Settings(db_path=tmp_path/'second.sqlite3',business_name='Second Business'),enable_mail_worker=False)) as other:
        assert verify(other,original).status_code==404
