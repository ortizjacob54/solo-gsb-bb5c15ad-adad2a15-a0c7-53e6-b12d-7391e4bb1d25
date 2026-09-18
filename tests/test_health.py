def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"].endswith(".db")


def test_root(client):
    body = client.get("/").json()
    assert body["service"] == "museum-light-budget"


def test_openapi_docs(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
