import time
import uuid
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.db import connect, initialize
from app.main import create_app
from app.mail import drain
from app.security import hash_password

PASSWORD = "test-only-long-password"

@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=tmp_path / "data/vicam.sqlite3")
    initialize(settings.db_path)
    with connect(settings.db_path) as db:
        db.execute("INSERT INTO staff(email,password_hash,can_issue_docs) VALUES(?,?,1)", ("staff@example.com", hash_password(PASSWORD)))
    with TestClient(create_app(settings, enable_mail_worker=False)) as c:
        c.settings = settings
        yield c

def payload(**changes):
    return dict(name="Example Client", email="client@example.com", service="CCTV & Surveillance",
                requirements="Cover the entrance and parking area.", consent=True, **changes)

def signin(client):
    result = client.post("/api/auth/login", json={"email":"staff@example.com", "password":PASSWORD})
    assert result.status_code == 200
    return {"X-CSRF-Token":result.json()["csrf"]}

def record(client, **changes):
    result = client.post("/api/enquiries", json=payload(**changes))
    assert result.status_code == 201, result.text
    with connect(client.settings.db_path) as db:
        return dict(db.execute("SELECT * FROM enquiries WHERE reference=?", (result.json()["reference"],)).fetchone())

def test_validation_and_public_privacy(client):
    assert client.get("/api/admin/enquiries").status_code == 401
    for key,value in [("consent",False),("consent",1),("service","Unknown"),("email","invalid"),("requirements","short"),("name","\n"),("website","spam")]:
        data=payload();data[key]=value
        assert client.post("/api/enquiries",json=data).status_code==422
    with connect(client.settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM enquiries").fetchone()[0]==0
    data=payload();data["admin"]=True
    assert client.post("/api/enquiries",json=data).status_code==422

def test_storage_idempotency_and_outbox(client):
    key=str(uuid.uuid4());headers={"X-Idempotency-Key":key}
    first=client.post("/api/enquiries",json=payload(),headers=headers)
    second=client.post("/api/enquiries",json=payload(),headers=headers)
    assert first.status_code==second.status_code==201
    assert first.json()==second.json()
    changed=payload();changed["requirements"]="A different brief with new coverage."
    assert client.post("/api/enquiries",json=changed,headers=headers).status_code==409
    with connect(client.settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM enquiries").fetchone()[0]==1
        assert db.execute("SELECT state FROM outbox").fetchone()[0]=="pending"
    assert set(first.json())=={"reference","message"}

def test_non_cctv_fields_are_removed(client):
    data=payload(site_type="School",coverage_areas="Private area");data["service"]="Software Development"
    assert client.post("/api/enquiries",json=data).status_code==201
    with connect(client.settings.db_path) as db:
        row=db.execute("SELECT site_type,coverage_areas FROM enquiries").fetchone()
        assert tuple(row)==("","")

def test_auth_csrf_status_notes_search_delete(client):
    item=record(client,organization="Example Ltd")
    path="/api/admin/enquiries/"+item["id"]
    assert client.get(path).status_code==401
    headers=signin(client)
    assert "HttpOnly" in client.post("/api/auth/login",json={"email":"staff@example.com","password":PASSWORD}).headers["set-cookie"]
    # The current browser session changed, so retrieve its current CSRF token.
    headers={"X-CSRF-Token":client.get("/api/auth/me").json()["csrf"]}
    assert client.patch(path,json={"status":"closed"}).status_code==403
    assert client.patch(path,json={"status":"in_progress"},headers=headers).status_code==200
    assert client.patch(path,json={"status":"invalid"},headers=headers).status_code==422
    note="<script>alert('test')</script> Follow up tomorrow."
    assert client.post(path+"/notes",json={"text":note},headers=headers).status_code==201
    assert client.get(path).json()["notes"][0]["text"]==note
    assert client.get("/api/admin/enquiries",params={"q":"Example Ltd","status":"in_progress"}).json()["total"]==1
    assert client.get("/api/admin/enquiries",params={"q":"%' OR 1=1--"}).json()["total"]==0
    assert client.delete(path,headers=headers).status_code==200
    assert client.get(path).status_code==404
    with connect(client.settings.db_path) as db:
        assert db.execute("SELECT count(*) FROM notes").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM outbox").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM submission_keys").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM audit WHERE action='delete_enquiry'").fetchone()[0]==1

def test_logout_expiry_and_disabled_account(client):
    headers=signin(client)
    assert client.post("/api/auth/logout",json={},headers=headers).status_code==200
    assert client.get("/api/auth/me").status_code==401
    signin(client)
    with connect(client.settings.db_path) as db:
        db.execute("UPDATE sessions SET expires=0")
    assert client.get("/api/auth/me").status_code==401
    signin(client)
    with connect(client.settings.db_path) as db:
        db.execute("UPDATE staff SET enabled=0")
    assert client.get("/api/auth/me").status_code==401

def test_origin_body_limit_and_rate_limits(client):
    assert client.post("/api/enquiries",json=payload(),headers={"Origin":"https://other.example"}).status_code==403
    assert client.post("/api/enquiries",content="{}",headers={"Content-Type":"text/plain"}).status_code==415
    huge=payload();huge["requirements"]="x"*40000
    assert client.post("/api/enquiries",json=huge).status_code==413
    for _ in range(10):
        assert client.post("/api/enquiries",json=payload()).status_code==201
    assert client.post("/api/enquiries",json=payload()).status_code==429

def test_login_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/auth/login",json={"email":"staff@example.com","password":"wrong"}).status_code==401
    assert client.post("/api/auth/login",json={"email":"staff@example.com","password":"wrong"}).status_code==429

def test_mail_failure_retry_and_ack(client):
    item=record(client)
    configured=replace(client.settings,smtp_host="smtp.example.com",mail_from="vicam@example.com",company_email="team@example.com")
    def fail(*args):raise RuntimeError("secret must not appear in database")
    assert drain(configured,sender=fail)==0
    with connect(configured.db_path) as db:
        row=db.execute("SELECT * FROM outbox").fetchone()
        assert row["state"]=="pending" and row["attempts"]==1
        assert "secret" not in row["last_error"]
        assert db.execute("SELECT count(*) FROM enquiries").fetchone()[0]==1
        db.execute("UPDATE outbox SET next_attempt=0")
    sent=[]
    assert drain(configured,sender=lambda *args:sent.append(args))==1
    assert sent[0][1]==item["reference"]
    with connect(configured.db_path) as db:
        assert db.execute("SELECT state FROM outbox").fetchone()[0]=="sent"
    assert drain(configured,sender=lambda *args:sent.append(args))==0

def test_mail_recovery_exhausted_lease(client):
    record(client)
    configured=replace(client.settings,smtp_host="smtp.example.com",mail_from="vicam@example.com",company_email="team@example.com")
    with connect(configured.db_path) as db:
        db.execute("UPDATE outbox SET state='sending',attempts=5,lease_at=0")
    assert drain(configured,sender=lambda *args:pytest.fail("Must not send exhausted work"))==0
    with connect(configured.db_path) as db:
        assert db.execute("SELECT state FROM outbox").fetchone()[0]=="failed"

def test_static_configuration_and_headers(client):
    assert client.get("/").status_code==200
    assert "/assets/website-backend.js" in client.get("/").text
    assert client.get("/admin").status_code==200
    assert "unsafe-inline" not in client.get("/admin").headers["content-security-policy"]
    assert client.get("/privacy").status_code==200
    assert client.get("/api/public/config").json()=={"enquiries_available":True,"company_email":None}
    assert client.get("/api/health").json()=={"status":"ok"}
    assert client.get("/api/auth/me").headers["cache-control"]=="no-store"
    assert client.get("/docs").status_code==404
    with pytest.raises(ValueError):
        replace(client.settings,production=True).validate()

def test_pagination_and_missing_enquiry(client):
    signin(client)
    assert client.get("/api/admin/enquiries?page=0").status_code==422
    assert client.get("/api/admin/enquiries/unknown").status_code==404
    assert client.get("/api/admin/enquiries?page=2").json()["items"]==[]

def test_production_cookie_and_origin(client):
    settings=replace(client.settings,production=True,secure_cookie=True,origin="https://vicam.example")
    with TestClient(create_app(settings,enable_mail_worker=False),base_url="https://vicam.example") as secured:
        result=secured.post("/api/auth/login",json={"email":"staff@example.com","password":PASSWORD},headers={"Origin":settings.origin})
        assert result.status_code==200
        assert "Secure" in result.headers["set-cookie"] and "SameSite=strict" in result.headers["set-cookie"]
        assert secured.get("/api/auth/me").status_code==200
        assert secured.get("/api/health").headers["strict-transport-security"]=="max-age=31536000"
