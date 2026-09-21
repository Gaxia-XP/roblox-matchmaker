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
from fastapi.responses import HTMLResponse
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


@app.get("/v1/queue")
def queue_list():
    con = db()
    try:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT user_id, party_id, mode, status, match_id,
                          EXTRACT(EPOCH FROM (now() - enqueued_at))::int AS wait_s
                   FROM mm_queue ORDER BY enqueued_at LIMIT 100"""
            )
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        con.close()
    return {"queue": rows}


@app.get("/v1/matches")
def matches_list(limit: int = 10):
    limit = max(1, min(limit, 50))
    con = db()
    try:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, mode, team_a, team_b, status, created_at
                   FROM mm_matches ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        con.close()
    for r in rows:
        r["created_at"] = str(r["created_at"])
    return {"matches": rows}


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Matchmaker Live</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:16px}
h1{font-size:20px}.card{background:#1c1c1c;border-radius:10px;padding:12px;margin:10px 0}
.team{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap}.p{background:#2a2a2a;border-radius:6px;padding:6px 10px}
.a .p{border-left:4px solid #4da3ff}.b .p{border-left:4px solid #ff5d5d}
.q{display:flex;gap:8px;flex-wrap:wrap}.small{color:#999;font-size:12px}
#st{position:sticky;top:0;background:#111;padding:8px 0}
</style></head><body>
<h1>Matchmaker Live <span class="small" id="ts"></span></h1>
<div id="st" class="small">connecting...</div>
<h2>Queue (<span id="qc">0</span>)</h2><div class="q" id="q"></div>
<h2>Recent matches</h2><div id="m"></div>
<script>
async function j(p){const r=await fetch(p);return r.json()}
async function tick(){
  try{
    const q=await j('/v1/queue');const m=await j('/v1/matches?limit=10');
    document.getElementById('st').textContent='live';
    document.getElementById('qc').textContent=q.queue.length;
    document.getElementById('q').innerHTML=q.queue.map(function(x){
      return '<div class="p">'+x.user_id+'<div class="small">'+x.status+' · '+x.wait_s+'s</div></div>'}).join('')||'<span class="small">empty</span>';
    document.getElementById('m').innerHTML=m.matches.map(function(x){
      return '<div class="card"><b>'+x.id+'</b> <span class="small">'+x.mode+' · '+x.status+'</span>'
      +'<div class="team a">'+x.team_a.map(function(p){return '<div class="p">'+p+'</div>'}).join('')+'</div>'
      +'<div class="team b">'+x.team_b.map(function(p){return '<div class="p">'+p+'</div>'}).join('')+'</div></div>'}).join('');
    document.getElementById('ts').textContent=new Date().toLocaleTimeString();
  }catch(e){document.getElementById('st').textContent='reconnecting...'}
}
setInterval(tick,3000);tick();
</script></body></html>"""


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


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
