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
    con.autocommit = False
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
        con.commit()
    except Exception:
        con.rollback()
        raise
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
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Matchmaking Control Room</title>
<style>
:root{
  --bg:#090d14;--surface:#101722;--surface-2:#151e2b;--line:#223043;
  --text:#f5f7fb;--muted:#8d9aab;--orange:#ff7a45;--green:#46d69a;
  --blue:#6aa9ff;--red:#ff6b87;--radius:16px
}
*{box-sizing:border-box}
body{
  margin:0;min-height:100vh;background:var(--bg);color:var(--text);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased
}
body:before{
  content:"";position:fixed;inset:0;pointer-events:none;
  background:radial-gradient(circle at 12% -10%,rgba(255,122,69,.12),transparent 34%),
             radial-gradient(circle at 90% 0,rgba(106,169,255,.08),transparent 28%)
}
.shell{position:relative;width:min(1240px,calc(100% - 40px));margin:0 auto;padding:28px 0 48px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:48px}
.brand{display:flex;align-items:baseline;gap:12px;font-weight:800;letter-spacing:.04em}
.brand-product{font-size:13px;color:var(--orange);text-transform:uppercase}
.brand-divider{width:1px;height:16px;background:var(--line)}
.brand-area{font-size:13px;color:var(--muted);font-weight:600}
.connection{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:12px}
.status-pill{
  display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid var(--line);
  border-radius:999px;background:rgba(16,23,34,.8);color:var(--text);font-weight:700
}
.status-dot{width:7px;height:7px;border-radius:50%;background:#758195}
.status-pill.live .status-dot{background:var(--green);box-shadow:0 0 0 4px rgba(70,214,154,.1)}
.status-pill.error .status-dot{background:var(--red)}
.hero{display:flex;justify-content:space-between;align-items:end;gap:24px;margin-bottom:28px}
.eyebrow{margin:0 0 10px;color:var(--orange);font-size:11px;font-weight:800;letter-spacing:.18em;text-transform:uppercase}
h1{margin:0;font-size:clamp(30px,4vw,48px);line-height:1.05;letter-spacing:-.04em}
.subtitle{margin:12px 0 0;color:var(--muted);font-size:15px;line-height:1.6}
.refresh-note{color:var(--muted);font-size:12px;white-space:nowrap}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;background:rgba(16,23,34,.72);margin-bottom:20px}
.metric{padding:20px 22px;min-height:116px;border-right:1px solid var(--line);display:flex;flex-direction:column;justify-content:space-between}
.metric:last-child{border-right:0}
.metric-label{color:var(--muted);font-size:12px;font-weight:650}
.metric-value{font-size:30px;font-weight:780;letter-spacing:-.035em}
.metric-value.text{font-size:18px;letter-spacing:-.015em}
.workspace{display:grid;grid-template-columns:minmax(300px,.8fr) minmax(0,1.6fr);gap:20px;align-items:start}
.panel{border:1px solid var(--line);border-radius:var(--radius);background:rgba(16,23,34,.82);overflow:hidden}
.panel-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 22px;border-bottom:1px solid var(--line)}
.panel-title{margin:0;font-size:15px;letter-spacing:-.01em}
.count{min-width:28px;padding:4px 8px;border-radius:999px;background:var(--surface-2);color:var(--muted);font-size:11px;font-weight:800;text-align:center}
.queue-list{padding:8px 0}
.queue-row{display:grid;grid-template-columns:36px minmax(0,1fr) auto;gap:12px;align-items:center;padding:13px 20px;border-bottom:1px solid rgba(34,48,67,.62)}
.queue-row:last-child{border-bottom:0}
.position{color:var(--muted);font-size:11px;font-weight:800}
.player-id{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:700}
.player-meta{margin-top:3px;color:var(--muted);font-size:11px}
.wait{font-variant-numeric:tabular-nums;color:var(--green);font-size:12px;font-weight:750}
.matches{padding:0 22px}
.match{padding:20px 0;border-bottom:1px solid var(--line)}
.match:last-child{border-bottom:0}
.match-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:15px}
.match-id{font-family:"SFMono-Regular",Consolas,monospace;font-size:12px;font-weight:700}
.match-meta{display:flex;gap:8px;align-items:center;color:var(--muted);font-size:11px}
.tag{padding:4px 7px;border-radius:6px;background:var(--surface-2);color:#c6d0dc;font-weight:750;text-transform:uppercase;letter-spacing:.06em}
.teams{display:grid;grid-template-columns:minmax(0,1fr) 28px minmax(0,1fr);gap:10px;align-items:center}
.team{display:grid;gap:7px}
.team-label{font-size:10px;font-weight:850;letter-spacing:.12em;text-transform:uppercase}
.team-a .team-label{color:var(--blue)}.team-b .team-label{color:var(--red)}
.roster{display:flex;gap:6px;flex-wrap:wrap}
.player{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--surface-2);font-size:11px;font-weight:650}
.team-a .player{border-left:2px solid var(--blue)}.team-b .player{border-left:2px solid var(--red)}
.versus{text-align:center;color:#5d6a7d;font-size:10px;font-weight:900}
.empty{padding:48px 22px;text-align:center}
.empty-title{margin:0 0 7px;font-size:14px}.empty-copy{margin:0;color:var(--muted);font-size:12px;line-height:1.5}
.error-banner{display:none;margin-bottom:20px;padding:12px 15px;border:1px solid rgba(255,107,135,.35);border-radius:10px;background:rgba(255,107,135,.08);color:#ffb1c0;font-size:12px}
.error-banner.show{display:block}
@media(max-width:820px){
  .shell{width:min(100% - 24px,680px);padding-top:20px}.topbar{margin-bottom:34px}
  .metrics{grid-template-columns:repeat(2,1fr)}.metric:nth-child(2){border-right:0}.metric:nth-child(-n+2){border-bottom:1px solid var(--line)}
  .workspace{grid-template-columns:1fr}.hero{align-items:start}.refresh-note{display:none}
}
@media(max-width:520px){
  .brand-area,.brand-divider,.connection>span:last-child{display:none}.topbar{margin-bottom:28px}
  .metrics{grid-template-columns:1fr}.metric{min-height:92px;border-right:0;border-bottom:1px solid var(--line)!important}.metric:last-child{border-bottom:0!important}
  .teams{grid-template-columns:1fr}.versus{display:none}.team-b{margin-top:6px}.matches{padding:0 16px}.panel-head{padding:17px 16px}
}
@media(prefers-reduced-motion:no-preference){.status-pill.live .status-dot{animation:pulse 2s infinite}@keyframes pulse{50%{box-shadow:0 0 0 7px rgba(70,214,154,0)}}}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div class="brand"><span class="brand-product">Cooking Battle</span><span class="brand-divider"></span><span class="brand-area">Matchmaking</span></div>
    <div class="connection"><span class="status-pill" id="status"><span class="status-dot"></span><span id="status-text">Connecting</span></span><span id="updated">Waiting for data</span></div>
  </header>
  <section class="hero">
    <div><p class="eyebrow">Live operations</p><h1>Matchmaking Control Room</h1><p class="subtitle">A live view of the 2v2 queue and recently formed matches.</p></div>
    <span class="refresh-note">Auto-refreshes every 3 seconds</span>
  </section>
  <div class="error-banner" id="error" role="alert">Live data is temporarily unavailable. Reconnecting automatically.</div>
  <section class="metrics" aria-label="Matchmaking summary" aria-live="polite">
    <article class="metric"><span class="metric-label">Waiting players</span><strong class="metric-value" id="waiting">—</strong></article>
    <article class="metric"><span class="metric-label">Longest wait</span><strong class="metric-value" id="longest">—</strong></article>
    <article class="metric"><span class="metric-label">Recent matches</span><strong class="metric-value" id="match-count">—</strong></article>
    <article class="metric"><span class="metric-label">Queue mode</span><strong class="metric-value text">2 versus 2</strong></article>
  </section>
  <section class="workspace">
    <article class="panel">
      <div class="panel-head"><h2 class="panel-title">Live queue</h2><span class="count" id="queue-count">0</span></div>
      <div class="queue-list" id="queue" aria-live="polite"><div class="empty"><p class="empty-title">Loading queue</p><p class="empty-copy">Waiting for the first update.</p></div></div>
    </article>
    <article class="panel">
      <div class="panel-head"><h2 class="panel-title">Recent matches</h2><span class="count" id="matches-count">0</span></div>
      <div class="matches" id="matches" aria-live="polite"><div class="empty"><p class="empty-title">Loading matches</p><p class="empty-copy">Recent activity will appear here.</p></div></div>
    </article>
  </section>
</main>
<script>
const byId=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const duration=seconds=>{const s=Math.max(0,Number(seconds)||0);if(s<60)return `${s}s`;const m=Math.floor(s/60);return m<60?`${m}m ${s%60}s`:`${Math.floor(m/60)}h ${m%60}m`};
const clock=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?'—':date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})};
async function json(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}
function empty(title,copy){return `<div class="empty"><p class="empty-title">${title}</p><p class="empty-copy">${copy}</p></div>`}
function renderQueue(rows){
  const waiting=rows.filter(row=>row.status==='waiting');
  byId('waiting').textContent=waiting.length;
  byId('longest').textContent=waiting.length?duration(Math.max(...waiting.map(row=>row.wait_s))):'0s';
  byId('queue-count').textContent=waiting.length;
  byId('queue').innerHTML=waiting.map((row,index)=>`<div class="queue-row"><span class="position">${String(index+1).padStart(2,'0')}</span><div><div class="player-id">${esc(row.user_id)}</div><div class="player-meta">${row.party_id?`Party ${esc(row.party_id)}`:'Solo player'} · ${esc(row.mode)}</div></div><span class="wait">${duration(row.wait_s)}</span></div>`).join('')||empty('Queue is clear','New players will appear here as soon as they join.');
}
function roster(players){return players.map(player=>`<span class="player">${esc(player)}</span>`).join('')}
function renderMatches(rows){
  byId('match-count').textContent=rows.length;
  byId('matches-count').textContent=rows.length;
  byId('matches').innerHTML=rows.map(match=>`<article class="match"><div class="match-head"><span class="match-id">${esc(match.id)}</span><div class="match-meta"><span class="tag">${esc(match.status)}</span><time>${clock(match.created_at)}</time></div></div><div class="teams"><div class="team team-a"><span class="team-label">Team A</span><div class="roster">${roster(match.team_a)}</div></div><span class="versus">VS</span><div class="team team-b"><span class="team-label">Team B</span><div class="roster">${roster(match.team_b)}</div></div></div></article>`).join('')||empty('No matches yet','The next completed pairing will appear here.');
}
async function refresh(){
  try{
    const [queueData,matchData]=await Promise.all([json('/v1/queue'),json('/v1/matches?limit=12')]);
    renderQueue(queueData.queue);renderMatches(matchData.matches);
    byId('status').className='status-pill live';byId('status-text').textContent='Live';
    byId('updated').textContent=`Updated ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;
    byId('error').classList.remove('show');
  }catch(error){
    byId('status').className='status-pill error';byId('status-text').textContent='Reconnecting';
    byId('updated').textContent='Last update failed';byId('error').classList.add('show');
  }
}
refresh();setInterval(refresh,3000);
</script>
</body>
</html>"""


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
           WHERE mode=%s AND status='waiting' ORDER BY enqueued_at LIMIT 24
           FOR UPDATE SKIP LOCKED""",
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
            con.autocommit = False
            try:
                with con.cursor() as cur:
                    for mode in MODE_TEAM_SIZE:
                        while True:
                            match_id = try_match(cur, mode)
                            con.commit()
                            if not match_id:
                                break
            except Exception:
                con.rollback()
                raise
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
