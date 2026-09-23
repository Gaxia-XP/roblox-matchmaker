import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

TEST_API_KEY = "test-matchmaker-key"
os.environ.setdefault("MATCHMAKER_API_KEY", TEST_API_KEY)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as mm

client = TestClient(mm.app)
client.headers["X-Matchmaker-Key"] = TEST_API_KEY
anonymous_client = TestClient(mm.app)


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


def join(uid, party="", source_server_id="", source_place_id=0):
    return client.post("/v1/queue/join", json={
        "user_id": uid,
        "party_id": party,
        "source_server_id": source_server_id,
        "source_place_id": source_place_id,
    }).json()


def join_party(party_id, member_ids, source_server_id="", source_place_id=0):
    return client.post(
        "/v1/queue/join-party",
        json={
            "party_id": party_id,
            "member_ids": member_ids,
            "mode": "2v2",
            "source_server_id": source_server_id,
            "source_place_id": source_place_id,
        },
    )


def make_match_from_two_source_servers():
    for index in range(2):
        join(f"server-a-{index}", source_server_id="server-A", source_place_id=100)
    result = None
    for index in range(2):
        result = join(f"server-b-{index}", source_server_id="server-B", source_place_id=200)
    assert result["state"] == "assigned"
    return result["match_id"]


def claim(match_id, source_server_id, place_id=999):
    return client.post(
        f"/v1/match/{match_id}/reservation/claim",
        json={"source_server_id": source_server_id, "destination_place_id": place_id},
    )


def complete(match_id, source_server_id, token, code="private-code", private_id="private-id"):
    return client.post(
        f"/v1/match/{match_id}/reservation/complete",
        json={
            "source_server_id": source_server_id,
            "reservation_token": token,
            "reserved_server_code": code,
            "private_server_id": private_id,
        },
    )


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


@pytest.mark.parametrize(("method", "path", "kwargs"), [
    ("post", "/v1/queue/join", {"json": {"user_id": "unauthorized"}}),
    ("post", "/v1/queue/leave", {"json": {"user_id": "unauthorized"}}),
    ("get", "/v1/queue/status", {"params": {"user_id": "unauthorized"}}),
    ("get", "/v1/match/missing", {}),
    ("post", "/v1/match/missing/reservation/claim", {
        "json": {"source_server_id": "server-A", "destination_place_id": 1},
    }),
    ("get", "/v1/match/missing/destination", {
        "params": {"source_server_id": "server-A"},
    }),
])
def test_server_endpoints_require_api_key(method, path, kwargs):
    response = getattr(anonymous_client, method)(path, **kwargs)

    assert response.status_code == 401
    assert response.json()["detail"] == "unauthorized"


def test_server_endpoints_reject_wrong_api_key():
    response = anonymous_client.get(
        "/v1/queue/status",
        params={"user_id": "unauthorized"},
        headers={"X-Matchmaker-Key": "wrong-key"},
    )

    assert response.status_code == 401


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


def test_atomic_party_join_with_two_solos():
    join("solo1")
    join("solo2")

    response = join_party("P1", ["p1a", "p1b"])

    assert response.status_code == 200
    result = response.json()
    assert result["state"] == "assigned"
    match = client.get(f"/v1/match/{result['match_id']}").json()
    assert {"p1a", "p1b"} in [set(match["team_a"]), set(match["team_b"])]


def test_party_join_persists_source_server_and_place_for_both_members():
    response = join_party("party-source", ["party-a", "party-b"], "party-server", 321)

    assert response.status_code == 200
    con = mm.db()
    try:
        with con.cursor() as cur:
            cur.execute(
                "SELECT user_id, source_server_id, source_place_id FROM mm_queue "
                "WHERE party_id=%s ORDER BY user_id",
                ("party-source",),
            )
            rows = cur.fetchall()
    finally:
        con.close()

    assert rows == [("party-a", "party-server", 321), ("party-b", "party-server", 321)]


def test_party_can_match_when_three_solos_are_already_waiting():
    for user_id in ["solo1", "solo2", "solo3"]:
        join(user_id)

    result = join_party("P1", ["p1a", "p1b"]).json()

    assert result["state"] == "assigned"
    match = client.get(f"/v1/match/{result['match_id']}").json()
    assert {"p1a", "p1b"} in [set(match["team_a"]), set(match["team_b"])]
    waiting = client.get("/v1/queue").json()["queue"]
    assert len([row for row in waiting if row["status"] == "waiting"]) == 1


def test_two_parties_form_opposing_teams():
    assert join_party("P1", ["p1a", "p1b"]).json()["state"] == "waiting"

    result = join_party("P2", ["p2a", "p2b"]).json()

    assert result["state"] == "assigned"
    match = client.get(f"/v1/match/{result['match_id']}").json()
    teams = [set(match["team_a"]), set(match["team_b"])]
    assert {"p1a", "p1b"} in teams
    assert {"p2a", "p2b"} in teams


def test_leave_party_removes_every_waiting_member():
    join_party("P1", ["p1a", "p1b"])

    response = client.post("/v1/queue/leave-party", json={"party_id": "P1"})

    assert response.json() == {"ok": True, "removed": 2}
    assert client.get("/v1/queue/status", params={"user_id": "p1a"}).json()["state"] == "idle"
    assert client.get("/v1/queue/status", params={"user_id": "p1b"}).json()["state"] == "idle"


@pytest.mark.parametrize("payload", [
    {"party_id": "", "member_ids": ["p1a", "p1b"]},
    {"party_id": "P1", "member_ids": ["p1a"]},
    {"party_id": "P1", "member_ids": ["p1a", "p1a"]},
])
def test_party_join_rejects_invalid_members(payload):
    assert client.post("/v1/queue/join-party", json=payload).status_code == 400


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

    assert all(result["state"] == "waiting" for result in results)
    assert match_count == 1
    assert duplicate_users == []


def test_concurrent_reservation_claims_have_one_winner():
    match_id = make_match_from_two_source_servers()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda server: claim(match_id, server), ["server-A", "server-B"]))

    assert sorted(response.json()["won"] for response in results) == [False, True]
    assert len({response.json()["state"] for response in results}) == 1


def test_only_participant_source_servers_can_claim_or_read_destination():
    match_id = make_match_from_two_source_servers()

    claim_response = claim(match_id, "unrelated-server")
    destination_response = client.get(
        f"/v1/match/{match_id}/destination", params={"source_server_id": "unrelated-server"}
    )

    assert claim_response.status_code == 403
    assert destination_response.status_code == 403


def test_wrong_owner_or_token_cannot_complete_reservation():
    match_id = make_match_from_two_source_servers()
    result = claim(match_id, "server-A").json()

    assert complete(match_id, "server-B", result["token"]).status_code == 409
    assert complete(match_id, "server-A", "wrong-token").status_code == 409
    assert client.get(
        f"/v1/match/{match_id}/destination", params={"source_server_id": "server-A"}
    ).json() == {"state": "claimed"}


def test_expired_reservation_claim_can_be_reclaimed():
    match_id = make_match_from_two_source_servers()
    first = claim(match_id, "server-A").json()
    con = mm.db()
    try:
        with con.cursor() as cur:
            cur.execute(
                "UPDATE mm_matches SET reservation_claim_expires_at=now()-interval '1 second' WHERE id=%s",
                (match_id,),
            )
    finally:
        con.close()

    second = claim(match_id, "server-B").json()

    assert first["won"] is True
    assert second["won"] is True
    assert second["token"] != first["token"]
    assert complete(match_id, "server-A", first["token"]).status_code == 409


def test_ready_reservation_is_idempotent_and_cannot_be_replaced():
    match_id = make_match_from_two_source_servers()
    won = claim(match_id, "server-A", place_id=999).json()
    payload = complete(match_id, "server-A", won["token"], "code-one", "private-one")

    assert payload.status_code == 200
    assert complete(match_id, "server-A", won["token"], "code-one", "private-one").json() == {
        "ok": True, "state": "ready"
    }
    assert complete(match_id, "server-A", won["token"], "replacement", "replacement").status_code == 409
    assert claim(match_id, "server-B", place_id=123).json() == {
        "won": False, "token": "", "state": "ready"
    }


def test_both_source_servers_read_same_ready_destination():
    match_id = make_match_from_two_source_servers()
    won = claim(match_id, "server-A", place_id=999).json()
    complete(match_id, "server-A", won["token"], "shared-code", "shared-private-id")

    first = client.get(
        f"/v1/match/{match_id}/destination", params={"source_server_id": "server-A"}
    )
    second = client.get(
        f"/v1/match/{match_id}/destination", params={"source_server_id": "server-B"}
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {
        "state": "ready",
        "destination_place_id": 999,
        "reserved_server_code": "shared-code",
        "private_server_id": "shared-private-id",
    }


def test_reserved_server_code_is_not_exposed_by_public_match_endpoints():
    match_id = make_match_from_two_source_servers()
    won = claim(match_id, "server-A").json()
    complete(match_id, "server-A", won["token"], "secret-reservation-code", "private-id")

    public_match = client.get(f"/v1/match/{match_id}")
    matches_list = client.get("/v1/matches")
    dashboard = client.get("/dashboard")

    assert "reserved_server_code" not in public_match.json()
    assert "secret-reservation-code" not in public_match.text
    assert "secret-reservation-code" not in matches_list.text
    assert "secret-reservation-code" not in dashboard.text
