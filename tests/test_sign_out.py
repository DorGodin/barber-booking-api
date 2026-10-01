from __future__ import annotations


def token_for(client, username: str, password: str) -> dict:
    resp = client.post("/auth/token", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_a_signed_out_token_stops_working_at_once(client, passwords):
    session = token_for(client, "customer", passwords["customer"])
    assert client.get("/me", headers=session).status_code == 200

    assert client.post("/auth/logout", headers=session).status_code == 204

    assert client.get("/me", headers=session).status_code == 401
    assert client.get("/bookings", headers=session).status_code == 401


def test_signing_out_on_one_device_leaves_the_others_signed_in(client, passwords):
    phone, laptop = (token_for(client, "customer", passwords["customer"]) for _ in range(2))

    client.post("/auth/logout", headers=phone)

    assert client.get("/me", headers=laptop).status_code == 200


def test_a_token_signed_out_twice_is_refused_the_second_time(client, passwords):
    session = token_for(client, "customer", passwords["customer"])
    client.post("/auth/logout", headers=session)

    assert client.post("/auth/logout", headers=session).status_code == 401
