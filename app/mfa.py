"""TOTP second factor: encrypted secrets, 30-second steps and replay protection."""
import base64
import hashlib
import hmac
import struct
import time
from cryptography.fernet import Fernet

def encrypt(settings,value):
    if not settings.data_encryption_key:raise ValueError('Configure DATA_ENCRYPTION_KEY before enrolling MFA or emailing invitations')
    return Fernet(settings.data_encryption_key.encode()).encrypt(value.encode()).decode()
def decrypt(settings,value):return Fernet(settings.data_encryption_key.encode()).decrypt(value.encode()).decode()
def code(secret,counter):
    raw=base64.b32decode(secret+'='*((-len(secret))%8));digest=hmac.new(raw,struct.pack('>Q',counter),hashlib.sha1).digest();i=digest[-1]&15
    return str((struct.unpack('>I',digest[i:i+4])[0]&0x7fffffff)%1000000).zfill(6)
def matching_counter(secret,value,last=-1):
    if not value.isascii() or len(value)!=6 or not value.isdigit():return None
    current=int(time.time())//30
    for counter in (current,current-1,current+1):
        if counter>last and hmac.compare_digest(code(secret,counter),value):return counter
    return None
