import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>assessment app</h1>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    return dist


def test_serves_spa_routes_and_static_assets_from_same_origin(tmp_path):
    client = TestClient(create_app(static_dir=make_dist(tmp_path)))

    assert client.get("/").text == "<h1>assessment app</h1>"
    assert client.get("/report/example").text == "<h1>assessment app</h1>"
    assert client.get("/assets/app.js").text == "console.log('app')"


def test_missing_asset_does_not_fall_back_to_spa(tmp_path):
    response = TestClient(create_app(static_dir=make_dist(tmp_path))).get("/assets/missing.js")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_api_route_never_falls_back_to_spa(tmp_path):
    response = TestClient(create_app(static_dir=make_dist(tmp_path))).get("/api/v1/unknown")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_static_server_rejects_encoded_path_traversal(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    response = TestClient(create_app(static_dir=make_dist(tmp_path))).get("/assets/%2e%2e/outside.txt")

    assert response.status_code == 404
    assert "private" not in response.text


def test_default_app_serves_the_real_frontend_build_and_referenced_asset():
    client = TestClient(create_app())

    index = client.get("/")
    asset_path = re.search(r'src="(/assets/[^"]+\.js)"', index.text)

    assert index.status_code == 200
    assert asset_path is not None
    asset = client.get(asset_path.group(1))
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("text/javascript")
