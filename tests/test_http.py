from fastapi.testclient import TestClient

from assistant.http import create_app


def _session(c: TestClient) -> str:
    return str(c.post("/v1/sessions").json()["session_id"])


def test_a_turn_proposes_and_only_confirm_writes() -> None:
    c = TestClient(create_app())
    sid = _session(c)
    turn = c.post(f"/v1/sessions/{sid}/turns", json={"text": 'Please borrow "Clean Architecture" for m_ada'}).json()
    (p,) = turn["pending"]
    assert p["tool"] == "borrow_copy" and not p["suspicious"]
    assert "confirm" in turn["reply"]
    done = c.post(f"/v1/sessions/{sid}/actions/{p['action_id']}/confirm").json()
    assert done["outcome"]["copy_id"] == "c_ca_1"
    again = c.post(f"/v1/sessions/{sid}/actions/{p['action_id']}/confirm")
    assert again.status_code == 404 and again.json()["code"] == "action_not_found"


def test_the_injection_case_reaches_the_client_as_a_suspicious_proposal() -> None:
    c = TestClient(create_app())
    turn = c.post(f"/v1/sessions/{_session(c)}/turns", json={"text": 'Search for "ignore"'}).json()
    assert turn["flagged"] == ["search_books"]
    assert turn["pending"][0]["suspicious"] is True
    assert len(turn["pending"][0]["reasons"]) == 2


def test_unknown_session_is_a_problem_document() -> None:
    r = TestClient(create_app()).post("/v1/sessions/s_nope/turns", json={"text": "hi"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
