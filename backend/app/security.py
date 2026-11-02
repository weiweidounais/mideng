import base64
import hashlib
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from cryptography.fernet import Fernet
from .config import config
from .db import db_session, get_entity, put_entity, LoginSession

COOKIE = "zhixu_session"
password_hasher=PasswordHash.recommended()
router=APIRouter()
_lock=threading.Lock()
_failures=defaultdict(deque)

@dataclass
class Actor:
    owner:str
    role:str
    csrf:str

def _fernet():
    key_path=config.data_dir/"encryption.key"
    if config.secret_key:
        key=base64.urlsafe_b64encode(hashlib.sha256(config.secret_key.encode()).digest())
    elif key_path.exists():
        key=key_path.read_bytes()
    else:
        key=Fernet.generate_key()
        try:
            fd=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"wb") as f:f.write(key)
        except FileExistsError:key=key_path.read_bytes()
    return Fernet(key)

def encrypt_secret(value:dict)->str:
    return _fernet().encrypt(json.dumps(value).encode()).decode()

def decrypt_secret(value:str)->dict:
    return json.loads(_fernet().decrypt(value.encode())) if value else {}

def initialize_security():
    _fernet()
    with db_session() as db:
        if get_entity(db,"setting","passwords",False):return
        values={"admin":config.admin_password or secrets.token_urlsafe(18),"manager":config.manager_password or secrets.token_urlsafe(18)}
        if any(len(p)<10 for p in values.values()):raise RuntimeError("管理口令至少需要 10 位，请检查服务端配置")
        put_entity(db,"setting",{"id":"passwords",**{r:password_hasher.hash(v) for r,v in values.items()}})
        # Only an owner-readable first-start file; never exposed by HTTP or stdout.
        path=config.data_dir/"bootstrap-passwords.json"
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,"w") as f:json.dump(values,f,ensure_ascii=False,indent=2)

def _read_actor(request:Request):
    token=request.cookies.get(COOKIE)
    if not token:return None
    with db_session() as db:
        row=db.get(LoginSession,hashlib.sha256(token.encode()).hexdigest())
        if not row:return None
        expires=row.expires_at
        if expires.tzinfo is None:expires=expires.replace(tzinfo=timezone.utc)
        if expires<datetime.now(timezone.utc):db.delete(row);return None
        return Actor(row.owner,row.role,row.csrf)

def current_session(request:Request)->Actor:
    actor=_read_actor(request)
    if not actor:raise HTTPException(401,"会话已过期，请重新选择角色")
    if request.method not in ("GET","HEAD","OPTIONS"):
        origin=request.headers.get("origin")
        if origin and origin not in config.origins:raise HTTPException(403,"请求来源不允许")
        if not secrets.compare_digest(request.headers.get("x-csrf-token",""),actor.csrf):raise HTTPException(403,"请求验证失败，请刷新页面")
    return actor

def require_manager(actor:Actor=Depends(current_session)):
    if actor.role not in ("admin","manager"):raise HTTPException(403,"需要知识库管理权限")
    return actor

def require_admin(actor:Actor=Depends(current_session)):
    if actor.role!="admin":raise HTTPException(403,"需要管理员权限")
    return actor

def _issue(request,response,role,owner=None):
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
    with db_session() as db:
        old=request.cookies.get(COOKIE)
        if old:
            old_row=db.get(LoginSession,hashlib.sha256(old.encode()).hexdigest())
            if old_row:
                owner=owner or old_row.owner
                db.delete(old_row)
        db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),owner=owner or secrets.token_urlsafe(24),role=role,csrf=csrf,expires_at=datetime.now(timezone.utc)+timedelta(hours=config.session_hours)))
    response.set_cookie(COOKIE,token,httponly=True,secure=config.cookie_secure,samesite="strict",max_age=config.session_hours*3600,path="/")
    return {"role":role,"csrf":csrf,"authenticated":role!="user"}

@router.get("/session")
def session(request:Request,response:Response):
    actor=_read_actor(request)
    if actor:return {"role":actor.role,"csrf":actor.csrf,"authenticated":actor.role!="user"}
    return _issue(request,response,"user")

class LoginBody(BaseModel):
    role:str
    password:str=Field(default="",max_length=256)

@router.post("/auth/login")
def login(body:LoginBody,request:Request,response:Response,actor:Actor=Depends(current_session)):
    if body.role not in ("user","manager","admin"):raise HTTPException(422,"角色不正确")
    if body.role=="user":return _issue(request,response,"user",actor.owner)
    key=(request.client.host if request.client else "local",body.role)
    with _lock:
        attempts=_failures[key];now=time.monotonic()
        while attempts and attempts[0]<now-600:attempts.popleft()
        if len(attempts)>=8:raise HTTPException(429,"口令尝试过多，请 10 分钟后重试")
    with db_session() as db:
        stored=get_entity(db,"setting","passwords").payload[body.role]
        valid=password_hasher.verify(body.password,stored)
    if not valid:
        with _lock:attempts.append(time.monotonic())
        raise HTTPException(401,"口令不正确，请检查后重试")
    with _lock:_failures.pop(key,None)
    return _issue(request,response,body.role,actor.owner)

@router.post("/auth/logout")
def logout(request:Request,response:Response,actor:Actor=Depends(current_session)):
    return _issue(request,response,"user",actor.owner)

class PasswordBody(BaseModel):
    role:str
    oldPassword:str=Field(min_length=1,max_length=256)
    password:str=Field(min_length=10,max_length=256)

@router.post("/auth/password")
def change_password(body:PasswordBody,actor:Actor=Depends(require_admin)):
    if body.role not in ("admin","manager"):raise HTTPException(422,"角色不正确")
    if len(body.password.strip())<10:raise HTTPException(422,"口令至少 10 位且不能仅包含空格")
    with db_session() as db:
        row=get_entity(db,"setting","passwords");data=dict(row.payload)
        if not password_hasher.verify(body.oldPassword,data[body.role]):raise HTTPException(400,"当前口令不正确")
        data[body.role]=password_hasher.hash(body.password);row.payload=data
        for session in db.query(LoginSession).filter(LoginSession.role==body.role).all():
            # Keep current administrator session so UI may refresh normally.
            if session.owner!=actor.owner:db.delete(session)
    return {"ok":True}
