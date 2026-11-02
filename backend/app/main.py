import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from .config import config
from .db import init_db,db_session
from .security import initialize_security,router as security_router
from .core import initialize_defaults,router as core_router

@asynccontextmanager
async def lifespan(app):
    init_db();initialize_security();initialize_defaults()
    from .local_embeddings import start_installed_engine, stop_owned_engine
    start_installed_engine()
    from .ingestion import recover_jobs,shutdown_jobs
    from .rag import recover_chat_runs,close_vector_store
    from .applications import recover_application_runs
    recover_chat_runs()
    recover_application_runs()
    recover_jobs()
    from .collaboration import _seed_if_empty
    try:
        _seed_if_empty()
    except Exception:
        logging.exception("collaboration seed failed")
    yield
    shutdown_jobs()
    close_vector_store()
    stop_owned_engine()

app=FastAPI(title="密灯 · 企业知识中台",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=config.origins,allow_credentials=True,allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],allow_headers=["Content-Type","X-CSRF-Token"])

@app.middleware("http")
async def response_security(request:Request,call_next):
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="same-origin"
    if request.url.path.startswith("/api/"):response.headers["Cache-Control"]="no-store"
    return response

@app.exception_handler(Exception)
async def unexpected_error(request:Request,error:Exception):
    # Do not emit SDK exceptions or request data: they may contain provider secrets.
    logging.error("Unhandled request error: %s %s",request.method,type(error).__name__)
    return JSONResponse(status_code=500,content={"detail":"服务处理失败，请查看对应请求状态后重试"})

@app.exception_handler(RequestValidationError)
async def validation_error(request:Request,error:RequestValidationError):
    # Pydantic's default error includes the submitted input, which may be a key/password.
    return JSONResponse(status_code=422,content={"detail":[{"loc":e["loc"],"msg":e["msg"],"type":e["type"]} for e in error.errors()]})

app.include_router(security_router,prefix="/api")
app.include_router(core_router,prefix="/api")
from .providers import router as providers_router
from .ingestion import router as ingestion_router
from .rag import router as rag_router
from .applications import router as applications_router
app.include_router(providers_router,prefix="/api")
app.include_router(ingestion_router,prefix="/api")
app.include_router(rag_router,prefix="/api")
app.include_router(applications_router,prefix="/api")
from .rag_workbench import router as rag_workbench_router
app.include_router(rag_workbench_router,prefix="/api")
from .collaboration import router as collaboration_router
app.include_router(collaboration_router,prefix="/api")
from .observability import router as observability_router
app.include_router(observability_router,prefix="/api")

@app.get("/api/health")
def health():
    from sqlalchemy import text
    with db_session() as db:db.execute(text("SELECT 1"))
    return {"status":"ok","version":"1.0.0","mode":"compose" if config.qdrant_url else "local-development"}

frontend=Path(__file__).resolve().parents[2]/"frontend"/"dist"
if frontend.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets",StaticFiles(directory=frontend/"assets"),name="frontend-assets")
    @app.get("/{path:path}")
    def serve_frontend(path:str):
        if path.startswith("api/"):return JSONResponse(status_code=404,content={"detail":"接口不存在"})
        file=(frontend/path).resolve()
        if frontend.resolve() in file.parents and file.is_file():return FileResponse(file)
        return FileResponse(frontend/"index.html", headers={"Cache-Control": "no-cache"})
