from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="StallSpan", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def _bad_request_on_invalid_body(_request: Request, _exc: RequestValidationError):
    # 请求体不合法（优先值非 1–9 整数、指向缺失、多字段等）一律按 400 中文拒绝，
    # 语义即「整次抬升拒绝」，不暴露 FastAPI 默认的 422 结构。
    return JSONResponse(
        status_code=400,
        content={"detail": "请求不合法：本轮临时优先须指向存在的摊主，且优先值为整数 1–9（整次抬升已拒绝）"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
