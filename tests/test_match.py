import os
import sys
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
