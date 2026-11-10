import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from command_demo import demo_routes


def test_interpretation_proposes_changes_to_the_demo_only(monkeypatch, tmp_path):
    def ask(text):
        return {"intent": "search_photos" if text == "cerca" else "add_tag", "slots": {"tag": "Giappone"}}

    monkeypatch.setitem(sys.modules, "command_model", SimpleNamespace(CommandModel=lambda _: SimpleNamespace(ask=ask)))
    app = FastAPI()
    app.include_router(demo_routes("fake-model", tmp_path / "demo.sqlite"))
    client = TestClient(app)

    proposed = client.post("/api/command-demo/interpret", json={"text": "aggiungi", "selection": ["1", "2"]}).json()
    assert proposed["proposal"] == {"action": "add_tag", "tag": "Giappone", "ids": ["1", "2"]}
    search = {"text": "cerca", "selection": []}
    assert client.post("/api/command-demo/interpret", json=search).json()["found"] == []
    assert client.post("/api/command-demo/tags", json={**proposed["proposal"], "ids": ["outside"]}).status_code == 422
    assert client.post("/api/command-demo/tags", json=proposed["proposal"]).json()["changed"] == 2
    assert client.post("/api/command-demo/interpret", json=search).json()["found"] == ["1", "2"]
