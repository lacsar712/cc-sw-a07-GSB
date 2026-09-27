import os
import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
)
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

SCHEMA_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    id serial PRIMARY KEY,
    lamp text NOT NULL,
    nominal_nm double precision NOT NULL,
    measured_nm double precision NOT NULL,
    status text NOT NULL,
    verdict text NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);
"""
SCHEMA_VOUCHERS = """
CREATE TABLE IF NOT EXISTS vouchers (
    id serial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    day date NOT NULL,
    status text NOT NULL DEFAULT 'valid',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    used_at timestamptz,
    job_id integer
);
"""
MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS voucher_code text NOT NULL DEFAULT ''",
]


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float
    voucher_code: str


def user_from_request(request: Request) -> dict:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "spectrum-wavelength-desk"}


@post("/api/login")
async def login(data: LoginIn) -> dict:
    u = USERS.get(data.username)
    if not u or not pwd.verify(data.password, u["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token = jwt.encode(
        {
            "sub": data.username,
            "role": u["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "role": u["role"], "username": data.username}


@get("/api/jobs")
async def list_jobs(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, voucher_code FROM jobs ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, voucher_code FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(row)


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可提交")
    code = data.voucher_code.strip().upper()
    if not code:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="提交必须挂当日口令券")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        voucher = conn.execute(
            "SELECT id, code, day, status FROM vouchers WHERE code = %s FOR UPDATE",
            (code,),
        ).fetchone()
        if not voucher:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="错券拒收：口令券不存在")
        if voucher["status"] != "valid":
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail="该券已作废，不得再次挂用")
        if voucher["day"] != now.date():
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="隔日旧券一律拒收")
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at, voucher_code)
            VALUES (%s,%s,%s,'pending','','',%s,%s,%s) RETURNING id
            """,
            (data.lamp.strip(), data.nominal_nm, data.measured_nm, user["username"], now, voucher["code"]),
        ).fetchone()
        conn.execute(
            "UPDATE vouchers SET status='void', used_at=%s, job_id=%s WHERE id=%s",
            (now, row["id"], voucher["id"]),
        )
        conn.commit()
        return {"id": row["id"], "status": "pending"}


@get("/api/vouchers")
async def list_vouchers(request: Request) -> dict:
    user_from_request(request)
    with connect() as conn:
        valid = conn.execute(
            "SELECT id, code, day, status, created_by, created_at FROM vouchers WHERE status='valid' ORDER BY id DESC"
        ).fetchall()
        voided = conn.execute(
            "SELECT id, code, day, status, created_by, created_at, used_at, job_id FROM vouchers WHERE status='void' ORDER BY id DESC"
        ).fetchall()
        return {"valid": list(valid), "void": list(voided)}


@post("/api/vouchers")
async def create_voucher(request: Request) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可发券")
    now = datetime.now(timezone.utc)
    day = now.date()
    with connect() as conn:
        for _ in range(5):
            code = f"CAL-{day:%Y%m%d}-{secrets.token_hex(3).upper()}"
            try:
                row = conn.execute(
                    """
                    INSERT INTO vouchers(code, day, status, created_by, created_at)
                    VALUES (%s,%s,'valid',%s,%s)
                    RETURNING id, code, day, status, created_by, created_at
                    """,
                    (code, day, user["username"], now),
                ).fetchone()
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                continue
            conn.commit()
            return dict(row)
        raise HTTPException(status_code=500, detail="发券失败，请重试")


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA_JOBS)
        conn.execute(SCHEMA_VOUCHERS)
        for stmt in MIGRATIONS:
            conn.execute(stmt)
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差内', 'seed', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08', 'seed', %s)
                """,
                (now, now),
            )
        conn.commit()


app = Litestar(
    route_handlers=[health, login, list_jobs, get_job, create_job, list_vouchers, create_voucher],
    on_startup=[on_startup],
)
