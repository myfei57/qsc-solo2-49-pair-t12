"""HTTP console endpoints."""

from __future__ import annotations

from flask.testing import FlaskClient


def test_state_and_static(client: FlaskClient) -> None:
    response = client.get("/api/state")
    assert response.status_code == 200
    assert response.get_json()["state"]["phase"] == "idle"
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    assert client.get("/missing.txt").status_code == 404


def test_read_only_endpoints(client: FlaskClient) -> None:
    for path in (
        "/api/report",
        "/api/machines",
        "/api/bus",
        "/api/store",
        "/api/events",
        "/api/audit",
        "/api/audit/summary",
        "/api/weld/seams",
        "/api/tension/persisted",
        "/api/strip/sag",
        "/api/sequence",
        "/api/pickle/dose/pending",
        "/api/pickle/dose/history",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.get_json()["ok"] is True


def test_missing_parameter_is_a_bad_request(client: FlaskClient) -> None:
    response = client.post("/api/entry/sample")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_domain_failure_is_a_conflict(client: FlaskClient) -> None:
    response = client.post("/api/entry/sample?value=abc")
    assert response.status_code == 400
    response = client.post("/api/pump/start?level=1.0")
    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["detail"]["code"] == "level-low"


def test_cycle_endpoint_runs_the_line(client: FlaskClient) -> None:
    response = client.post(
        "/api/cycle",
        query_string={
            "coil": "C-77",
            "target": 90,
            "level": 4.5,
            "voltage": 24,
            "current": 300,
            "speed": 1.4,
        },
    )
    assert response.status_code == 200
    sequence = response.get_json()["sequence"]
    assert sequence["label"] == "production"
    assert all(step["ok"] for step in sequence["steps"])
    state = client.get("/api/state").get_json()["state"]
    assert state["phase"] == "idle"
    assert state["weld"]["seam"]


def test_cycle_without_a_coil_is_rejected(client: FlaskClient) -> None:
    response = client.post("/api/cycle", query_string={"target": 90})
    assert response.status_code == 400


def test_weld_alarm_flow(client: FlaskClient) -> None:
    assert client.post("/api/weld/confirm").status_code == 409
    client.post("/api/cycle?coil=C-1&target=90&level=4.5&voltage=24&current=300&speed=1.4")
    client.post("/api/entry/sample?value=12")
    alarm = client.post("/api/weld/alarm").get_json()
    assert alarm["alarms"] == ["weld-overcurrent"]
    assert client.post("/api/weld/release").status_code == 409
    cleared = client.post("/api/weld/clear").get_json()
    assert cleared["cleared"] is True
    assert client.post("/api/weld/release").status_code == 200


def test_events_stream_records_bus_traffic(client: FlaskClient) -> None:
    client.post("/api/entry/sample?value=5")
    events = client.get("/api/events").get_json()["events"]
    assert isinstance(events, list)
    client.post("/api/cycle?coil=C-1&target=90&level=4.5&voltage=24&current=300&speed=1.4")
    events = client.get("/api/events").get_json()["events"]
    kinds = {event["kind"] for event in events}
    assert {"arc", "weld", "tension", "pump", "stop"} <= kinds


def test_audit_query_filters_by_kind(client: FlaskClient) -> None:
    client.post("/api/cycle?coil=C-1&target=90&level=4.5&voltage=24&current=300&speed=1.4")
    response = client.get("/api/audit?kind=arc&limit=5")
    events = response.get_json()["events"]
    assert events and all(event["kind"] == "arc" for event in events)
    summary = client.get("/api/audit/summary").get_json()["summary"]
    assert summary["arc"] >= 1


def test_store_view_lists_keys(client: FlaskClient) -> None:
    client.post("/api/cycle?coil=C-1&target=90&level=4.5&voltage=24&current=300&speed=1.4")
    view = client.get("/api/store").get_json()
    assert "weld.record" in view["keys"]
    assert "TensionSnapshot" in view["recordTypes"]


def test_machines_view(client: FlaskClient) -> None:
    machines = client.get("/api/machines").get_json()["machines"]
    assert set(machines) == {"weld", "pump", "dryer", "tension"}
    assert machines["weld"]["state"] == "idle"


def test_bus_view_reports_subscribers(client: FlaskClient) -> None:
    view = client.get("/api/bus").get_json()
    assert view["subscribers"]["arc"] >= 1


def test_taper_weight_and_eta(client: FlaskClient) -> None:
    taper = client.post("/api/exit/taper?base=40&diameter=120").get_json()
    assert taper["taper"] > 40.0
    weight = client.post(
        "/api/exit/weight?entry=2.5&exit=2.3&width=1250&length=4200"
    ).get_json()
    assert weight["weight"] > 0.0
    client.post("/api/strip/advance?delta=20")
    client.post("/api/strip/speed?speed=2")
    eta = client.get("/api/strip/eta?target=120").get_json()
    assert eta["eta"] > 0.0


def test_sequence_clear_endpoint(client: FlaskClient) -> None:
    client.post("/api/entry/sample?value=1")
    assert client.post("/api/sequence/clear").status_code == 200
    assert client.get("/api/sequence").get_json()["sequence"]["steps"] == []


def test_dose_plan_submit_review_withdraw(client: FlaskClient) -> None:
    # A single low reading after several on-target ones must not by itself
    # force a dose; the endpoint plans from the captured window.
    client.post("/api/pump/resume?level=10.0")
    response = client.post("/api/pickle/dose?volume=20&target=12")
    assert response.status_code == 200
    plan = response.get_json()["plan"]
    assert plan["required"] is True
    assert plan["status"] == "pending"
    assert plan["basis"]["samples"]
    plan_id = plan["planId"]

    pending = client.get("/api/pickle/dose/pending").get_json()["plan"]
    assert pending["planId"] == plan_id
    reviewed = client.get(f"/api/pickle/dose/review?id={plan_id}").get_json()["plan"]
    assert reviewed["basis"]["average"] == pending["basis"]["average"]

    withdrawn = client.post("/api/pickle/dose/withdraw?reason=观察回升").get_json()["plan"]
    assert withdrawn["status"] == "withdrawn"
    assert withdrawn["reason"] == "观察回升"
    assert client.get("/api/pickle/dose/pending").get_json()["plan"] is None

    history = client.get("/api/pickle/dose/history").get_json()["plans"]
    assert len(history) == 1
    assert history[0]["planId"] == plan_id
    assert history[0]["basis"]["samples"]


def test_dose_plan_confirm_then_replan_conflict(client: FlaskClient) -> None:
    client.post("/api/pump/resume?level=4.0")
    first = client.post("/api/pickle/dose?volume=20&target=10").get_json()["plan"]
    duplicate = client.post("/api/pickle/dose?volume=20&target=10")
    assert duplicate.status_code == 409
    assert duplicate.get_json()["detail"]["code"] == "dose-pending"

    confirmed = client.post("/api/pickle/dose/confirm").get_json()["plan"]
    assert confirmed["status"] == "confirmed"
    assert client.post("/api/pickle/dose/confirm").status_code == 409

    # Once the trend window has been refilled with on-target readings the
    # endpoint must refuse another dose even if an old low sample lingers.
    for _ in range(8):
        client.post("/api/pump/resume?level=12.0")
    refused = client.post("/api/pickle/dose?volume=20&target=10")
    assert refused.status_code == 409
    assert refused.get_json()["detail"]["code"] == "dose-not-required"
