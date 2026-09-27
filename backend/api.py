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
)
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
# “当日”按东八区日历日判定，容器内 UTC 也不受影响
CN_TZ = timezone(timedelta(hours=8))
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS coupons (
    id serial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    valid_date date NOT NULL,
    status text NOT NULL DEFAULT 'valid',
    void_reason text NOT NULL DEFAULT '',
    voided_by text NOT NULL DEFAULT '',
    voided_at timestamptz,
    used_by_job integer,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS coupon_id integer;
"""


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


def today_cn() -> "datetime.date":
    return datetime.now(CN_TZ).date()


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float
    coupon_code: str = ""


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


def require_writer(request: Request) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="观察账号只许翻阅，不许发券/作废/提交")
    return user


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
            """
            SELECT j.id, j.lamp, j.nominal_nm, j.measured_nm, j.status, j.verdict,
                   j.reason, j.created_by, c.code AS coupon_code
            FROM jobs j
            LEFT JOIN coupons c ON c.id = j.coupon_id
            ORDER BY j.id DESC
            """
        ).fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT j.id, j.lamp, j.nominal_nm, j.measured_nm, j.status, j.verdict,
                   j.reason, j.created_by, c.code AS coupon_code
            FROM jobs j
            LEFT JOIN coupons c ON c.id = j.coupon_id
            WHERE j.id = %s
            """,
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(row)


@get("/api/coupons")
async def list_coupons(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, code, valid_date, status, void_reason, voided_by,
                   voided_at, used_by_job, created_by, created_at
            FROM coupons ORDER BY id DESC
            """
        ).fetchall()
        result = []
        today = today_cn()
        for r in rows:
            d = dict(r)
            d["valid_date"] = d["valid_date"].isoformat()
            d["voided_at"] = d["voided_at"].isoformat() if d["voided_at"] else None
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            # 展示用状态：隔日旧券即便未核销也不能再挂
            d["usable"] = d["status"] == "valid" and d["valid_date"] == today.isoformat()
            result.append(d)
        return result


@post("/api/coupons")
async def create_coupon(request: Request) -> dict:
    user = require_writer(request)
    day = today_cn()
    code = f"CAL-{day:%Y%m%d}-{secrets.token_hex(3).upper()}"
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO coupons(code, valid_date, status, created_by, created_at)
            VALUES (%s, %s, 'valid', %s, %s)
            RETURNING id, code, valid_date, status, void_reason, voided_by,
                      voided_at, used_by_job, created_by, created_at
            """,
            (code, day, user["username"], now),
        ).fetchone()
        conn.commit()
    d = dict(row)
    d["valid_date"] = d["valid_date"].isoformat()
    d["voided_at"] = None
    d["created_at"] = d["created_at"].isoformat()
    d["usable"] = True
    return d


@post("/api/coupons/{coupon_id:int}/void")
async def void_coupon(request: Request, coupon_id: int) -> dict:
    user = require_writer(request)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute(
            "SELECT id, status FROM coupons WHERE id = %s FOR UPDATE",
            (coupon_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="券不存在")
        if row["status"] != "valid":
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="该券已在作废簿中")
        conn.execute(
            """
            UPDATE coupons
            SET status='void', void_reason='校准员手动作废', voided_by=%s, voided_at=%s
            WHERE id=%s
            """,
            (user["username"], now, coupon_id),
        )
        conn.commit()
    return {"id": coupon_id, "status": "void"}


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = require_writer(request)
    code = (data.coupon_code or "").strip()
    if not code:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="提交校准必须挂一张仍有效的当日校准口令券")
    lamp = data.lamp.strip()
    if not lamp:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="灯种不能为空")

    now = datetime.now(timezone.utc)
    today = today_cn()
    with connect() as conn:
        # 行锁串行化同一张券的并发挂用
        coupon = conn.execute(
            "SELECT id, code, valid_date, status FROM coupons WHERE code = %s FOR UPDATE",
            (code,),
        ).fetchone()
        if not coupon:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="错券：查无此口令券，投单拒收")
        if coupon["status"] != "valid":
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="该券已记入作废簿，不得再次挂用，投单拒收")
        if coupon["valid_date"] != today:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=f"隔日旧券（券面日期 {coupon['valid_date'].isoformat()}），一律拒收",
            )

        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason,
                             created_by, created_at, coupon_id)
            VALUES (%s,%s,%s,'pending','','',%s,%s,%s) RETURNING id
            """,
            (lamp, data.nominal_nm, data.measured_nm, user["username"], now, coupon["id"]),
        ).fetchone()
        # 入队成功：一次性券立即核销，记入作废簿，不得再次挂用
        conn.execute(
            """
            UPDATE coupons
            SET status='void', void_reason=%s, voided_by=%s, voided_at=%s, used_by_job=%s
            WHERE id=%s
            """,
            (f"已用于任务 #{row['id']}", user["username"], now, row["id"], coupon["id"]),
        )
        conn.commit()
        return {"id": row["id"], "status": "pending", "coupon_id": coupon["id"]}


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
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
        cn = conn.execute("SELECT COUNT(*) AS n FROM coupons").fetchone()["n"]
        if cn == 0:
            now = datetime.now(timezone.utc)
            day = today_cn()
            conn.execute(
                """
                INSERT INTO coupons(code, valid_date, status, void_reason, voided_by, voided_at,
                                    created_by, created_at)
                VALUES
                (%s, %s, 'valid', '', '', NULL, 'seed', %s),
                (%s, %s, 'valid', '', '', NULL, 'seed', %s),
                (%s, %s, 'void', '种子：演示已作废券', 'seed', %s, 'seed', %s)
                """,
                (
                    f"CAL-{day:%Y%m%d}-SEED01", day, now,
                    f"CAL-{(day - timedelta(days=1)):%Y%m%d}-SEEDOLD", day - timedelta(days=1), now,
                    f"CAL-{day:%Y%m%d}-SEEDVOID", day, now, now,
                ),
            )
        conn.commit()


app = Litestar(
    route_handlers=[health, login, list_jobs, get_job, list_coupons, create_coupon, void_coupon, create_job],
    on_startup=[on_startup],
)
