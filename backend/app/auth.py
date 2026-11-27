import base64, hashlib, hmac, json, os, time
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .db import get_db
from .models import RevokedSession, User

SECRET = os.getenv("VALTIERA_SECRET", "local-development-secret-change-before-deploy").encode()
bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    salt=os.urandom(16); key=hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return base64.urlsafe_b64encode(salt+key).decode()

def verify_password(password: str, encoded: str) -> bool:
    try:
        raw=base64.urlsafe_b64decode(encoded); salt, expected=raw[:16],raw[16:]
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256",password.encode(),salt,310_000),expected)
    except Exception: return False

def issue_token(user: User) -> str:
    payload=base64.urlsafe_b64encode(json.dumps({"sub":user.id,"exp":int(time.time())+60*60*12}).encode()).rstrip(b"=")
    signature=hmac.new(SECRET,payload,hashlib.sha256).digest()
    return payload.decode()+"."+base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

def current_user(credentials: HTTPAuthorizationCredentials|None=Depends(bearer), db: Session=Depends(get_db)) -> User:
    if not credentials: raise HTTPException(401,"Sign in to continue",headers={"WWW-Authenticate":"Bearer"})
    try:
        payload,signature=credentials.credentials.split(".",1); raw=payload.encode()
        expected=base64.urlsafe_b64encode(hmac.new(SECRET,raw,hashlib.sha256).digest()).rstrip(b"=").decode()
        if not hmac.compare_digest(signature,expected): raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(payload+"="*(-len(payload)%4)))
        if data["exp"]<time.time(): raise ValueError()
        if db.get(RevokedSession,hashlib.sha256(credentials.credentials.encode()).hexdigest()): raise ValueError()
    except Exception: raise HTTPException(401,"Invalid or expired session",headers={"WWW-Authenticate":"Bearer"})
    user=db.get(User,int(data["sub"]))
    if not user: raise HTTPException(401,"Invalid or expired session",headers={"WWW-Authenticate":"Bearer"})
    return user

def optional_user(credentials: HTTPAuthorizationCredentials|None=Depends(bearer), db: Session=Depends(get_db)) -> User|None:
    if not credentials: return None
    try: return current_user(credentials,db)
    except HTTPException: return None
