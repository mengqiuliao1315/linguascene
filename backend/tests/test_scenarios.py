def test_list_scenarios(auth_client):
    response = auth_client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert len(scenarios) == 12
    slugs = {s["slug"] for s in scenarios}
    assert "ordering-coffee" in slugs
    assert "job-interview" in slugs
    assert "doctor-visit" in slugs
    assert "team-meeting" in slugs


def test_scenario_detail_has_tasks(auth_client):
    scenarios = auth_client.get("/api/scenarios").json()
    coffee = next(s for s in scenarios if s["slug"] == "ordering-coffee")

    response = auth_client.get(f"/api/scenarios/{coffee['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["ai_role"] == "Barista"
    assert len(body["tasks"]) == 6
    assert body["tasks"][0]["task_key"] == "choose_drink"


def test_unknown_scenario_404(auth_client):
    assert auth_client.get("/api/scenarios/99999").status_code == 404


def test_filter_by_category(auth_client):
    response = auth_client.get("/api/scenarios", params={"category": "Travel"})
    assert response.status_code == 200
    assert all(s["category"] == "Travel" for s in response.json())
