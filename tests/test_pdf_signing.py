import hashlib
import io
from dataclasses import replace
from urllib.parse import urlsplit
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.serialization import Encoding
from asn1crypto import x509
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from test_backend import client,signin
from test_crm import create,profile,BASE
from app.db import connect
from app.main import create_app
from app.pdf_signing import create_test_certificate

@pytest.fixture
def signed_client(client,tmp_path):
    path=tmp_path/'private.p12';cert=create_test_certificate(path,'test-password-123')
    settings=replace(client.settings,pdf_signing_mode='test',pdf_signing_pfx=str(path),pdf_signing_password='test-password-123')
    with TestClient(create_app(settings,enable_mail_worker=False)) as c:
        c.settings=settings;c.certificate=cert;yield c

def quotation(c):
    h=signin(c);p=profile(c,h)
    q=create(c,'quotes',dict(client_id=p['id'],title='Annual IT support',description='Support and maintain office computers.',amount_minor=10440000,status='sent'),h)
    return h,q

def issue(c,h,q):return c.post('/api/admin/documents/quotes/'+q['id']+'/signed-pdf',json={},headers=h)

def validation(c,pdf):
    sig=PdfFileReader(io.BytesIO(pdf)).embedded_signatures[0]
    # Explicit trust is limited to this test, never a production trust claim.
    context=ValidationContext(trust_roots=[x509.Certificate.load(c.certificate.public_bytes(Encoding.DER))],allow_fetching=False,revocation_mode='soft-fail')
    return validate_pdf_signature(sig,signer_validation_context=context)

def test_signed_original_validation_tampering_and_withdrawal(signed_client):
    c=signed_client;h,q=quotation(c);r=issue(c,h,q);assert r.status_code==201,r.text
    meta=r.json();pdf=c.get(meta['download_url']).content
    assert pdf.startswith(b'%PDF') and hashlib.sha256(pdf).hexdigest()==meta['pdf_sha256']
    status=validation(c,pdf)
    assert status.intact and status.valid and status.trusted and status.docmdp_ok and status.bottom_line
    # Change the title metadata without breaking PDF parsing: covered bytes fail integrity.
    assert q['reference'].encode() in pdf
    changed=pdf.replace(q['reference'].encode(),b'X'+q['reference'][1:].encode(),1)
    assert not validation(c,changed).intact
    token=urlsplit(meta['verification_url']).fragment
    c.cookies.clear();v=c.get('/api/verify/'+token).json()
    assert v['signing_mode']=='test' and v['pdf_sha256']==meta['pdf_sha256']
    assert c.get(v['download_url']).content==pdf
    h=signin(c)
    assert c.post('/api/admin/documents/copies/'+meta['id']+'/revoke',json={},headers=h).status_code==200
    assert c.get(v['download_url']).status_code==410
    assert c.get(meta['download_url']).content==pdf # staff still retain original
    assert c.delete(BASE+'quotes/'+q['id'],headers=h).status_code==200
    with connect(c.settings.db_path) as db:assert db.execute('SELECT count(*) FROM pdf_artifacts').fetchone()[0]==0

def test_permission_and_signing_configuration(client):
    c=client;h,q=quotation(c)
    assert issue(c,h,q).status_code==409
    with connect(c.settings.db_path) as db:db.execute('UPDATE staff SET can_issue_docs=0')
    assert not c.get('/api/auth/me').json()['can_issue_documents']
    assert issue(c,h,q).status_code==403
    assert c.post('/api/admin/documents/quotes/'+q['id']+'/copies',json={},headers=h).status_code==403

def test_signing_failure_is_atomic_and_draft_cannot_be_signed(signed_client):
    c=signed_client;h,q=quotation(c)
    with connect(c.settings.db_path) as db:db.execute("UPDATE quotes SET status='draft' WHERE id=?",(q['id'],))
    assert issue(c,h,q).status_code==409
    with connect(c.settings.db_path) as db:db.execute("UPDATE quotes SET status='sent' WHERE id=?",(q['id'],))
    from pathlib import Path
    Path(c.settings.pdf_signing_pfx).unlink()
    assert issue(c,h,q).status_code==409
    with connect(c.settings.db_path) as db:
        assert db.execute('SELECT count(*) FROM document_copies').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM pdf_artifacts').fetchone()[0]==0

def test_pdf_storage_integrity(client):
    c=client;h,q=quotation(c)
    meta=c.post('/api/admin/documents/quotes/'+q['id']+'/copies',json={},headers=h).json()
    token=urlsplit(meta['verification_url']).fragment
    with connect(c.settings.db_path) as db:db.execute('UPDATE pdf_artifacts SET pdf_bytes=? WHERE copy_id=?',(b'changed',meta['id']))
    assert c.get('/api/verify/'+token).json()['state']=='unavailable'
    assert c.get('/api/verify/'+token+'/pdf').status_code==410
    assert c.get(meta['download_url']).status_code==409

def test_production_rejects_local_test_identity(signed_client):
    s=signed_client.settings
    with pytest.raises(ValueError):replace(s,production=True).validate()
    with pytest.raises(ValueError):replace(s,production=True,pdf_signing_mode='certificate').validate()


def test_incremental_changes_break_certification(signed_client):
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils import generic
    c=signed_client;h,q=quotation(c);meta=issue(c,h,q).json();pdf=c.get(meta['download_url']).content
    writer=IncrementalPdfFileWriter(io.BytesIO(pdf))
    page_ref=writer.root['/Pages']['/Kids'].raw_get(0)
    page=page_ref.get_object()
    page[generic.pdf_name('/Contents')]=writer.add_object(generic.StreamObject(stream_data=b'BT /F1 20 Tf 50 700 Td (ALTERED AMOUNT) Tj ET'))
    writer.mark_update(page_ref)
    altered=io.BytesIO();writer.write(altered)
    status=validation(c,altered.getvalue())
    assert status.intact and status.valid and not status.docmdp_ok and not status.bottom_line
