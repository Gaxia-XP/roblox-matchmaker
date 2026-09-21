import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as mm

client = TestClient(mm.app)


def setup_module():
    mm.init_schema()


def teardown_function():
    con = mm.db()
    try:
        with con.cursor() as cur:
            cur.execute("DELETE FROM mm_queue")
            cur.execute("DELETE FROM mm_matches")
    finally:
        con.close()


def join(uid, party=""):
    return client.post("/v1/queue/join", json={"user_id": uid, "party_id": party}).json()


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_dashboard_renders_operator_overview():
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Cooking Battle // Match Control" in response.text
    assert "WAITING PLAYERS" in response.text
    assert 'aria-live="polite"' in response.text


def test_player_profiles_return_roblox_names_and_avatars(monkeypatch):
    mm.PROFILE_CACHE.clear()

    def fake_fetch(url, data=None):
        if url == mm.ROBLOX_USERS_URL:
            assert data == {"userIds": [2973404790], "excludeBannedUsers": False}
            return {"data": [{"id": 2973404790, "name": "Gaxia", "displayName": "Gaxia XP"}]}
        assert "userIds=2973404790" in url
        return {"data": [{"targetId": 2973404790, "state": "Completed", "imageUrl": "https://example.com/avatar.png"}]}

    monkeypatch.setattr(mm, "fetch_roblox_json", fake_fetch)

    response = client.get("/v1/players", params={"user_ids": "2973404790,sim-player"})

    assert response.json() == {"players": {
        "2973404790": {
            "user_id": "2973404790",
            "username": "Gaxia",
            "display_name": "Gaxia XP",
            "avatar_url": "https://example.com/avatar.png",
        },
        "sim-player": {
            "user_id": "sim-player",
            "username": "sim-player",
            "display_name": "sim-player",
            "avatar_url": "",
        },
    }}


def test_four_solos_form_match():
    for i in range(3):
        assert join(f"solo{i}")["state"] == "waiting"
    r = join("solo3")
    assert r["state"] == "assigned" and r["match_id"]
    m = client.get(f"/v1/match/{r['match_id']}").json()
    assert len(m["team_a"]) == 2 and len(m["team_b"]) == 2
    assert client.get("/v1/queue/status", params={"user_id": "solo0"}).json()["state"] == "assigned"


def test_party_stays_together():
    join("p1a", party="P1")
    join("p1b", party="P1")
    join("s1")
    r = join("s2")
    assert r["state"] == "assigned"
    m = client.get(f"/v1/match/{r['match_id']}").json()
    teams = [set(m["team_a"]), set(m["team_b"])]
    assert {"p1a", "p1b"} in teams


def test_leave_and_rejoin():
    join("u1")
    assert client.post("/v1/queue/leave", json={"user_id": "u1"}).json()["removed"] == 1
    assert client.get("/v1/queue/status", params={"user_id": "u1"}).json()["state"] == "idle"
    assert join("u1")["state"] == "waiting"


def test_concurrent_match_attempts_assign_each_waiter_once(monkeypatch):
    con = mm.db()
    try:
        with con.cursor() as cur:
            cur.executemany(
                "INSERT INTO mm_queue (user_id) VALUES (%s)",
                [(f"seed{i}",) for i in range(4)],
            )
    finally:
        con.close()

    real_db = mm.db
    select_barrier = threading.Barrier(2)

    class BarrierCursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self._wait_after_fetch = False

        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            self._wait_after_fetch = (
                "FROM mm_queue" in normalized
                and "status='waiting'" in normalized
                and "ORDER BY enqueued_at" in normalized
            )
            return self._cursor.execute(query, params)

        def fetchall(self):
            rows = self._cursor.fetchall()
            if self._wait_after_fetch:
                select_barrier.wait(timeout=5)
            return rows

        def __getattr__(self, name):
            return getattr(self._cursor, name)

        def __enter__(self):
            self._cursor.__enter__()
            return self

        def __exit__(self, *args):
            return self._cursor.__exit__(*args)

    class BarrierConnection:
        def __init__(self, connection):
            object.__setattr__(self, "_connection", connection)

        def cursor(self, *args, **kwargs):
            return BarrierCursor(self._connection.cursor(*args, **kwargs))

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def __setattr__(self, name, value):
            return setattr(self._connection, name, value)

    monkeypatch.setattr(mm, "db", lambda: BarrierConnection(real_db()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda uid: mm.join(mm.JoinReq(user_id=uid)), ["late1", "late2"]))

    con = real_db()
    try:
        with con.cursor() as cur:
            cur.execute("SELECT count(*) FROM mm_matches")
            match_count = cur.fetchone()[0]
            cur.execute(
                """SELECT user_id, count(*)
                   FROM mm_matches, jsonb_array_elements_text(team_a || team_b) AS user_id
                   GROUP BY user_id HAVING count(*) > 1"""
            )
            duplicate_users = cur.fetchall()
    finally:
        con.close()

    assert sum(bool(result["match_id"]) for result in results) == 1
    assert match_count == 1
    assert duplicate_users == []
