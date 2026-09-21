"""Central matchmaker for Roblox (MVP: 2v2).

Endpoints (called by game servers via HttpService):
  GET  /healthz
  POST /v1/queue/join   {user_id, party_id?, mode?} -> {state, position}
  POST /v1/queue/leave  {user_id}                   -> {ok}
  GET  /v1/queue/status?user_id=                    -> {state, match_id?}
  GET  /v1/match/{match_id}                         -> {teams, status}

Matching: greedy oldest-first, parties kept together when they fit.
A match = 2 teams x 2 players.
"""
import os
import threading
import time
import uuid

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DATABASE_URL = os.environ["DATABASE_URL"]
MODE_TEAM_SIZE = {"2v2": 2}

app = FastAPI(title="roblox-matchmaker")


def db():
    con = psycopg2.connect(DATABASE_URL)
    con.autocommit = True
    return con


def init_schema():
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        sql = f.read()
    con = db()
    try:
        with con.cursor() as cur:
            cur.execute(sql)
    finally:
        con.close()


class JoinReq(BaseModel):
    user_id: str
    party_id: str = ""
    mode: str = "2v2"


class LeaveReq(BaseModel):
    user_id: str


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/queue/join")
def join(req: JoinReq):
    if req.mode not in MODE_TEAM_SIZE:
        raise HTTPException(400, "unknown mode")
    con = db()
    try:
        with con.cursor() as cur:
            cur.execute(
                """INSERT INTO mm_queue (user_id, party_id, mode, status)
                   VALUES (%s, %s, %s, 'waiting')
                   ON CONFLICT (user_id) DO UPDATE
                   SET party_id=EXCLUDED.party_id, mode=EXCLUDED.mode,
                       status='waiting', match_id='', enqueued_at=now()""",
                (req.user_id, req.party_id, req.mode),
            )
            match_id = try_match(cur, req.mode)
            cur.execute("SELECT count(*) FROM mm_queue WHERE mode=%s AND status='waiting'",
                        (req.mode,))
            position = cur.fetchone()[0]
    finally:
        con.close()
    return {"state": "assigned" if match_id else "waiting",
            "match_id": match_id or "", "position": position}


@app.post("/v1/queue/leave")
def leave(req: LeaveReq):
    con = db()
    try:
        with con.cursor() as cur:
            cur.execute("DELETE FROM mm_queue WHERE user_id=%s", (req.user_id,))
            removed = cur.rowcount
    finally:
        con.close()
    return {"ok": True, "removed": removed}


@app.get("/v1/queue/status")
def status(user_id: str):
    con = db()
    try:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT status, match_id FROM mm_queue WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
    finally:
        con.close()
    if not row:
        return {"state": "idle", "match_id": ""}
    return {"state": row["status"], "match_id": row["match_id"]}


@app.get("/v1/match/{match_id}")
def match(match_id: str):
    con = db()
    try:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, mode, team_a, team_b, status FROM mm_matches WHERE id=%s",
                        (match_id,))
            row = cur.fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(404, "no such match")
    return dict(row)


def try_match(cur, mode):
    """Greedily form one 2v2 match from oldest waiters. Returns match_id or ''."""
    size = MODE_TEAM_SIZE[mode]
    cur.execute(
        """SELECT user_id, party_id FROM mm_queue
           WHERE mode=%s AND status='waiting' ORDER BY enqueued_at LIMIT 24""",
        (mode,),
    )
    waiters = cur.fetchall()
    # group by party (solo = own party key)
    parties = {}
    order = []
    for uid, pid in waiters:
        key = pid or ("solo:" + uid)
        if key not in parties:
            parties[key] = []
            order.append(key)
        parties[key].append(uid)
    team_a, team_b = [], []
    used_keys = set()
    for key in order:
        members = parties[key]
        if len(team_a) + len(members) <= size and key not in used_keys:
            team_a += members
            used_keys.add(key)
        elif len(team_b) + len(members) <= size and key not in used_keys:
            team_b += members
            used_keys.add(key)
        if len(team_a) == size and len(team_b) == size:
            break
    if len(team_a) != size or len(team_b) != size:
        return ""
    match_id = "m_" + uuid.uuid4().hex[:12]
    cur.execute(
        "INSERT INTO mm_matches (id, mode, team_a, team_b) VALUES (%s,%s,%s,%s)",
        (match_id, mode, psycopg2.extras.Json(team_a), psycopg2.extras.Json(team_b)),
    )
    all_uids = team_a + team_b
    cur.execute(
        "UPDATE mm_queue SET status='assigned', match_id=%s WHERE user_id = ANY(%s)",
        (match_id, all_uids),
    )
    return match_id


def sweeper(interval=5):
    """Background pass so matches form even when joins trickle in."""
    while True:
        try:
            con = db()
            try:
                with con.cursor() as cur:
                    for mode in MODE_TEAM_SIZE:
                        while try_match(cur, mode):
                            pass
            finally:
                con.close()
        except Exception:
            pass
        time.sleep(interval)


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    init_schema()
    threading.Thread(target=sweeper, daemon=True).start()
    yield


app.router.lifespan_context = lifespan
