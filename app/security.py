import hashlib
import hmac
import secrets
import time
from fastapi import HTTPException
from .db import connect

ITERATIONS = 600_000

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"

def check_password(password, encoded):
    try:
        method, iterations, salt, digest = encoded.split("$")
        if method != "pbkdf2_sha256":
            return False
        result = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(result, digest)
    except (ValueError, TypeError):
        return False

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

# A fixed dummy hash keeps unknown-account login work comparable to known accounts.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))

def rate_limit(path, action, identifier, limit, seconds):
    window = int(time.time()) // seconds
    key = token_hash(action + ":" + identifier)
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM rate_limits WHERE expires<?", (int(time.time()),))
        row = db.execute("SELECT window,count FROM rate_limits WHERE key=?", (key,)).fetchone()
        count = row["count"] if row and row["window"] == window else 0
        if count >= limit:
            raise HTTPException(429, "Too many requests. Please try again later.", headers={"Retry-After": str(seconds)})
        db.execute("INSERT INTO rate_limits(key,window,count,expires) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET window=excluded.window,count=excluded.count,expires=excluded.expires", (key, window, count + 1, (window+1)*seconds))
