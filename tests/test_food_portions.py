import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


class FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, results):
        self.results = iter(results)
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((str(query), params))
        return next(self.results, FakeResult())

    def close(self):
        pass


@pytest.fixture
def make_client():
    clients = []

    def _make_client(results):
        fake_db = FakeDB(results)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)
        clients.append(client)
        return client, fake_db

    yield _make_client

    for client in clients:
        client.close()
    app.dependency_overrides.pop(get_db, None)


def test_food_portions_returns_verified_portions(make_client):
    food_id = "11111111-1111-4111-8111-111111111111"

    client, fake_db = make_client([
        FakeResult(row={"food_id": food_id}),
        FakeResult(rows=[
            {
                "portion_id": "22222222-2222-4222-8222-222222222222",
                "portion_name_th": "หนึ่งถ้วย",
                "portion_name_en": "one cup",
                "unit_name": "ถ้วย",
                "weight_g": 150,
                "source_note": "example source",
                "verification_status": "reviewed",
            }
        ]),
    ])

    response = client.get(f"/foods/{food_id}/portions")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["food_id"] == food_id
    assert data["count"] == 1
    assert data["items"][0]["weight_g"] == 150
    assert data["items"][0]["verification_status"] == "reviewed"
    assert len(fake_db.queries) == 2


def test_food_portions_returns_404_when_food_not_found(make_client):
    food_id = "11111111-1111-4111-8111-111111111111"
    client, fake_db = make_client([
        FakeResult(row=None),
    ])

    response = client.get(f"/foods/{food_id}/portions")

    assert response.status_code == 404
    assert len(fake_db.queries) == 1


def test_food_portions_returns_empty_list_when_no_verified_portions(
    make_client,
):
    food_id = "11111111-1111-4111-8111-111111111111"
    client, fake_db = make_client([
        FakeResult(row={"food_id": food_id}),
        FakeResult(rows=[]),
    ])

    response = client.get(f"/foods/{food_id}/portions")

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["items"] == []
