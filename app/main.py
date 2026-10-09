import asyncio
import hashlib
import hmac
import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .config import ROOT, Settings, load_settings
from .db import audit, connect, initialize, now
from .mail import worker
from .access import authorize
from .mfa import decrypt,matching_counter
from .models import Enquiry, Login, Note, Status, StatusUpdate
from .security import DUMMY_HASH, check_password, rate_limit, token_hash

COOKIE = "vicam_session"
PRIVACY_VERSION = "enquiries-client-v2"

class BodyLimit:
    def __init__(self, app, limit=32768):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["method"] in {"GET", "HEAD"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            limit = 2850000 if scope["path"] == "/api/client/files" or (scope["path"].startswith("/api/admin/experience/clients/") and scope["path"].endswith("/files")) else self.limit
            if len(body) > limit:
                return await JSONResponse({"detail": "Request too large"}, 413)(scope, receive, send)
            if not message.get("more_body"):
                break
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)

def create_app(settings: Settings | None = None, enable_mail_worker=True):
    settings = (settings or load_settings()).validate()

    @asynccontextmanager
    async def lifespan(app):
        initialize(settings.db_path)
        with connect(settings.db_path) as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (int(time.time()),))
        task = asyncio.create_task(worker(settings)) if enable_mail_worker and settings.email_ready else None
        from .operations import backup_worker
        backup_task=asyncio.create_task(backup_worker(settings)) if settings.backup_directory else None
        yield
        if backup_task:
            backup_task.cancel()
            with suppress(asyncio.CancelledError):await backup_task
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="VICAM Enquiries", version="2.8.2", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            if origin and origin != settings.origin:
                return JSONResponse({"detail": "Origin not allowed"}, 403)
            if request.method in {"POST", "PATCH", "PUT"} and request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "Use application/json"}, 415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(("/api/", "/admin", "/client")):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith(("/verify/", "/api/verify/", "/client", "/api/client/")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        inline = " 'unsafe-inline'" if request.url.path in {"/", "/vicam_home_with_education.html"} else ""
        response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'{inline}; style-src 'self'{inline}; img-src 'self' data:; frame-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; connect-src 'self'"
        if settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def staff(request: Request):
        token = request.cookies.get(COOKIE, "")
        if not token:
            raise HTTPException(401, "Sign in to continue")
        with connect(settings.db_path) as db:
            session = db.execute("SELECT s.*,u.email,u.can_issue_docs,u.role FROM sessions s JOIN staff u ON u.id=s.staff_id WHERE s.token_hash=? AND s.expires>? AND u.enabled=1", (token_hash(token), int(time.time()))).fetchone()
        if not session:
            raise HTTPException(401, "Session expired. Sign in again.")
        if request.method not in {"GET", "HEAD"}:
            csrf_value = request.headers.get("x-csrf-token", "")
            if not csrf_value.isascii() or not hmac.compare_digest(csrf_value, session["csrf"]):
                raise HTTPException(403, "Session verification failed. Reload the dashboard.")
        authorize(session["role"],request.url.path,request.method)
        return dict(session)

    @app.get("/api/health")
    def health():
        with connect(settings.db_path) as db:
            db.execute("SELECT id FROM staff LIMIT 1")
        return {"status": "ok"}

    @app.get("/api/public/config")
    def public_config():
        return {"enquiries_available": True, "company_email": settings.company_email or None}

    @app.post("/api/enquiries", status_code=201)
    def create_enquiry(data: Enquiry, request: Request):
        ip = request.client.host if request.client else "unknown"
        rate_limit(settings.db_path, "enquiry", ip, 10, 3600)
        if data.website:
            raise HTTPException(422, "Unable to accept this enquiry")
        identifier, reference, stamp = uuid.uuid4().hex, "VIC-" + secrets.token_hex(5).upper(), now()
        values = data.model_dump(exclude={"consent", "website"})
        raw_key = request.headers.get("x-idempotency-key", str(uuid.uuid4()))
        try:
            submission_key = token_hash(str(uuid.UUID(raw_key)))
        except ValueError:
            raise HTTPException(422, "Invalid submission key")
        payload_hash = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        with connect(settings.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT k.payload_hash,e.reference FROM submission_keys k JOIN enquiries e ON e.id=k.enquiry_id WHERE k.key_hash=?", (submission_key,)).fetchone()
            if previous:
                if not hmac.compare_digest(previous["payload_hash"], payload_hash):
                    raise HTTPException(409, "The brief changed. Refresh and submit it again.")
                return {"reference": previous["reference"], "message": "Your brief has been received by VICAM."}
            db.execute("""INSERT INTO enquiries(id,reference,created_at,updated_at,name,email,service,requirements,organization,phone,timeline,site_type,existing_system,coverage_areas,service_context,consent_at,privacy_version)
                        VALUES(:id,:reference,:stamp,:stamp,:name,:email,:service,:requirements,:organization,:phone,:timeline,:site_type,:existing_system,:coverage_areas,:service_context,:stamp,:privacy)""",
                       dict(values, id=identifier, reference=reference, stamp=stamp, privacy=PRIVACY_VERSION))
            db.execute("INSERT INTO outbox(enquiry_id) VALUES(?)", (identifier,))
            db.execute("INSERT INTO submission_keys VALUES(?,?,?)", (submission_key,payload_hash,identifier))
        # Success means durable storage, not guaranteed email delivery.
        return {"reference": reference, "message": "Your brief has been received by VICAM."}

    @app.post("/api/auth/login")
    def login(data: Login, request: Request, response: Response):
        email = str(data.email).lower()
        ip = request.client.host if request.client else "unknown"
        rate_limit(settings.db_path, "login-ip", ip, 30, 900)
        rate_limit(settings.db_path, "login-account", ip + ":" + email, 5, 900)
        with connect(settings.db_path) as db:
            user = db.execute("SELECT * FROM staff WHERE email=? AND enabled=1", (email,)).fetchone()
        valid = check_password(data.password, user["password_hash"] if user else DUMMY_HASH)
        if not valid or not user:
            raise HTTPException(401, "Email or password is incorrect")
        if user['mfa_secret']:
            with connect(settings.db_path) as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute('SELECT mfa_secret,mfa_last_counter FROM staff WHERE id=?',(user['id'],)).fetchone()
                try:counter=matching_counter(decrypt(settings,current['mfa_secret']),data.otp,current['mfa_last_counter'])
                except Exception:raise HTTPException(503,'Second-factor configuration unavailable; contact the administrator')
                if counter is None:raise HTTPException(401,'Enter a current authenticator code; each code can be used once')
                db.execute('UPDATE staff SET mfa_last_counter=? WHERE id=?',(counter,user['id']))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        duration = settings.session_hours * 3600
        with connect(settings.db_path) as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token_hash(token), user["id"], csrf, int(time.time())+duration))
            audit(db, user["id"], "sign_in", "staff")
        response.set_cookie(COOKIE, token, max_age=duration, httponly=True, secure=settings.secure_cookie, samesite="strict", path="/")
        return {"email": email, "csrf": csrf}

    @app.get("/api/auth/me")
    def me(user=Depends(staff)):
        return {"email": user["email"], "csrf": user["csrf"], "email_notifications_configured": settings.email_ready,"role":user["role"],"can_issue_documents":bool(user["can_issue_docs"]) and user["role"] in {"admin","finance"},"pdf_signing_mode":settings.pdf_signing_mode}

    @app.post("/api/auth/logout")
    def logout(response: Response, user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
        response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookie, httponly=True, samesite="strict")
        return {"ok": True}

    @app.get("/api/admin/enquiries")
    def enquiries(status: Status | None = None, q: str = Query("", max_length=100), page: int = Query(1, ge=1), user=Depends(staff)):
        clauses, args = [], []
        if status:
            clauses.append("e.status=?")
            args.append(status)
        if q.strip():
            clauses.append("(e.name LIKE ? ESCAPE '\\' OR e.email LIKE ? ESCAPE '\\' OR e.reference LIKE ? ESCAPE '\\' OR e.organization LIKE ? ESCAPE '\\')")
            term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args.extend([term]*4)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with connect(settings.db_path) as db:
            total = db.execute("SELECT count(*) FROM enquiries e"+where, args).fetchone()[0]
            rows = db.execute("SELECT e.id,e.reference,e.name,e.organization,e.service,e.status,e.created_at,o.state AS notification FROM enquiries e LEFT JOIN outbox o ON o.enquiry_id=e.id"+where+" ORDER BY e.created_at DESC,e.id DESC LIMIT 25 OFFSET ?", [*args,(page-1)*25]).fetchall()
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": 25}

    def get_enquiry(db, identifier):
        row = db.execute("SELECT e.*,o.state AS notification,o.attempts AS notification_attempts,o.last_error AS notification_error FROM enquiries e LEFT JOIN outbox o ON o.enquiry_id=e.id WHERE e.id=?", (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, "Enquiry not found")
        return dict(row)

    @app.get("/api/admin/enquiries/{identifier}")
    def detail(identifier: str, user=Depends(staff)):
        with connect(settings.db_path) as db:
            item = get_enquiry(db, identifier)
            item["notes"] = [dict(r) for r in db.execute("SELECT n.text,n.created_at,u.email AS author FROM notes n JOIN staff u ON u.id=n.staff_id WHERE enquiry_id=? ORDER BY n.id", (identifier,))]
            audit(db, user["staff_id"], "view_enquiry", item["reference"])
        return item

    @app.patch("/api/admin/enquiries/{identifier}")
    def change_status(identifier: str, data: StatusUpdate, user=Depends(staff)):
        with connect(settings.db_path) as db:
            item = get_enquiry(db, identifier)
            db.execute("UPDATE enquiries SET status=?,updated_at=? WHERE id=?", (data.status, now(), identifier))
            audit(db, user["staff_id"], "status_"+data.status, item["reference"])
        return {"status": data.status}

    @app.post("/api/admin/enquiries/{identifier}/notes", status_code=201)
    def add_note(identifier: str, data: Note, user=Depends(staff)):
        with connect(settings.db_path) as db:
            item = get_enquiry(db, identifier)
            db.execute("INSERT INTO notes(enquiry_id,staff_id,text,created_at) VALUES(?,?,?,?)", (identifier,user["staff_id"],data.text,now()))
            audit(db, user["staff_id"], "add_note", item["reference"])
        return {"ok": True}

    @app.post("/api/admin/enquiries/{identifier}/retry-notification")
    def retry(identifier: str, user=Depends(staff)):
        if not settings.email_ready:
            raise HTTPException(409, "Email notifications are not configured")
        with connect(settings.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            item = get_enquiry(db, identifier)
            if item["notification"] == "sending":
                raise HTTPException(409, "A notification is being sent")
            db.execute("UPDATE outbox SET state='pending',attempts=0,next_attempt=0,last_error='' WHERE enquiry_id=?", (identifier,))
            audit(db, user["staff_id"], "retry_notification", item["reference"])
        return {"ok": True}

    @app.delete("/api/admin/enquiries/{identifier}")
    def delete(identifier: str, user=Depends(staff)):
        with connect(settings.db_path) as db:
            item = get_enquiry(db, identifier)
            db.execute("DELETE FROM enquiries WHERE id=?", (identifier,))
            audit(db, user["staff_id"], "delete_enquiry", item["reference"])
        return {"ok": True}

    @app.get("/")
    @app.get("/vicam_home_with_education.html")
    def website():
        return FileResponse(ROOT / "static/index.html")

    @app.get("/admin")
    def dashboard():
        return FileResponse(ROOT / "static/admin.html")

    @app.get("/privacy")
    def privacy():
        return FileResponse(ROOT / "static/privacy.html")

    from .crm import router
    app.include_router(router(settings, staff))
    from .assistant import router as assistant_router
    app.include_router(assistant_router(settings,staff))
    from .operations import router as operations_router
    app.include_router(operations_router(settings,staff))
    from .delivery import router as delivery_router
    app.include_router(delivery_router(settings,staff))
    from .documents import routers
    for document_router in routers(settings, staff):
        app.include_router(document_router)

    @app.get("/admin/clients")
    def clients_dashboard():
        return FileResponse(ROOT / "static/crm.html")

    from .experience import routers as experience_routers
    for experience_router in experience_routers(settings, staff):
        app.include_router(experience_router)

    @app.get("/admin/operations")
    def operations_page():return FileResponse(ROOT/"static/operations.html")

    from .education import router as education_router
    app.include_router(education_router(settings,staff))

    @app.get("/admin/education")
    def education_dashboard():return FileResponse(ROOT/"static/education.html")

    app.mount("/assets", StaticFiles(directory=ROOT / "static/assets"), name="assets")
    return app
