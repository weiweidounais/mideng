"""Local pilot entrypoint. Intentionally never mounts legacy AI or unscoped routers."""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .pilot_api import make_router
from .pilot_policy import read_policy
from .pilot_service import Store


class HealthOut(BaseModel):
    status: str
    stage: str


class RuntimeOut(BaseModel):
    model_enabled: bool
    data_mode: str
    stage: str


def make_app(database_url=None, worker=True):
    data = Path(os.environ.get('PILOT_DATA_DIR', Path(__file__).resolve().parents[1] / '.runtime' / 'pilot'))
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    from .mobile_boundary import mobile_host
    mobile = mobile_host(data, os.environ.get('PILOT_MOBILE_QA_HOST'))
    policy = read_policy()
    if policy['model_enabled']:
        raise RuntimeError('F10尚未实现，不允许启动已启用模型的入口')
    store = Store(database_url or f'sqlite:///{data / "pilot.db"}')
    stopped = asyncio.Event()

    async def dispatch():
        last_scan=0.0
        while not stopped.is_set():
            try:
                await asyncio.to_thread(store.drain)
                from .cost_service import run_job
                await asyncio.to_thread(run_job,store)
                from .evidence_export import run_export
                await asyncio.to_thread(run_export,store)
                from .knowledge_api import run_knowledge_job
                await asyncio.to_thread(run_knowledge_job,store)
                if time.monotonic()-last_scan>=60:
                    def scan():
                        from .handoff_service import reconcile
                        with store.transaction(write=True) as db:
                            reconcile(db)
                            from .assurance_service import reconcile as reconcile_assurance
                            reconcile_assurance(db)
                    await asyncio.to_thread(scan)
                    last_scan=time.monotonic()
            except Exception as error:
                logging.error('Background dispatch failed: %s', type(error).__name__)
            try:
                await asyncio.wait_for(stopped.wait(), timeout=1)
            except TimeoutError:
                pass

    @asynccontextmanager
    async def lifespan(app):
        store.migrate()
        stopped.clear()
        task = asyncio.create_task(dispatch()) if worker else None
        yield
        stopped.set()
        if task:
            await task
        store.engine.dispose()

    app = FastAPI(title='密灯 · 嘉元项目协同中台', version='0.2.1', lifespan=lifespan)
    app.state.store = store
    app.state.model_enabled = policy['model_enabled']
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]']+([mobile] if mobile else []))
    allowed_origins = {'http://127.0.0.1:18410', 'http://localhost:18410',
                       'http://127.0.0.1:15173', 'http://localhost:15173'}

    def error_response(request, status, detail):
        body = detail if isinstance(detail, dict) else {'code': 'REQUEST_REJECTED', 'message': str(detail)}
        return JSONResponse(status_code=status, content={'error': {**body, 'request_id': request.state.request_id}})

    @app.middleware('http')
    async def boundary(request, call_next):
        request.state.request_id = str(uuid4())
        if mobile and request.url.scheme != 'https':
            return error_response(request, 403, {'code':'HTTPS_REQUIRED','message':'手机验收入口仅允许HTTPS'})
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            origin = request.headers.get('origin')
            same_origin = str(request.base_url).rstrip('/')
            if origin and origin not in allowed_origins and origin != same_origin:
                return error_response(request, 403, {'code': 'ORIGIN_REJECTED', 'message': '请求来源不允许'})
            if not origin and request.headers.get('sec-fetch-site') == 'cross-site':
                return error_response(request, 403, {'code': 'ORIGIN_REJECTED', 'message': '请求来源不允许'})
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        actor_id = getattr(request.state, 'actor_id', None)
        if actor_id and error.status_code in {403, 404}:
            import hashlib
            from .pilot_models import Audit
            from .pilot_service import uid
            with store.transaction(write=True) as db:
                db.add(Audit(id=uid(), project_id=None, actor_id=actor_id,
                    action='access.denied', object_id=hashlib.sha256(request.url.path.encode()).hexdigest()[:16],
                    revision=0, request_id=request.state.request_id))
        return error_response(request, error.status_code, error.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(request, 422, {'code': 'VALIDATION_ERROR', 'message': '请检查输入内容',
            'field_errors': [{'field': '.'.join(str(v) for v in e['loc']), 'message': e['msg']} for e in error.errors()]})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        return error_response(request, 409, {'code': 'CONSTRAINT_CONFLICT', 'message': '记录关联或唯一性冲突，请核对后重试'})

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        logging.error('Pilot request %s failed: %s', request.state.request_id, type(error).__name__)
        return error_response(request, 500, {'code': 'SERVER_ERROR', 'message': '处理失败，请按请求编号核对结果'})

    app.include_router(make_router(store))

    @app.get('/api/health', response_model=HealthOut)
    def health():
        with store.transaction() as db:
            db.execute(text('SELECT 1'))
        return {'status': 'ok', 'stage': '3-4'}

    @app.get('/api/runtime', response_model=RuntimeOut)
    def runtime():
        return {'model_enabled': app.state.model_enabled, 'data_mode': 'synthetic-or-redacted', 'stage': '3-4'}

    frontend = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if (frontend / 'assets').is_dir() and (frontend / 'index.html').is_file():
        app.mount('/assets', StaticFiles(directory=frontend / 'assets'), name='assets')
        @app.get('/{path:path}')
        def webpage(path: str):
            if path.startswith('api/'):
                raise HTTPException(404, {'code': 'NOT_IMPLEMENTED', 'message': '该能力尚未交付'})
            asset = (frontend / path).resolve()
            if frontend.resolve() in asset.parents and asset.is_file():
                return FileResponse(asset)
            return FileResponse(frontend / 'index.html')
    return app


app = make_app()
