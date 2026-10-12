"""The shop's shelf: the owner keeps the products, a customer reads them, and one with a
booking ahead asks for a product to be kept for it."""

from __future__ import annotations

import base64

import pytest

from tests.conftest import HAIRCUT, a_second_barber, at, book, local_day
from tests.test_reviews import past_booking

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def make(client, owner, **fields):
    body = {"name": "ווקס מט", "line": "100 מ״ל", "price_minor": 6500}
    return client.post("/products", headers=owner, json={**body, **fields})


@pytest.fixture
def wax(client, owner) -> str:
    return make(client, owner).json()["id"]


@pytest.fixture
def ahead(client, customer, barber, services) -> str:
    return book(client, customer, barber, services[HAIRCUT]["id"], at(local_day(3), "10:00")).json()["id"]


def keep(client, headers, booking, product):
    return client.put(f"/bookings/{booking}/products/{product}", headers=headers)


def test_the_owner_adds_a_product_and_a_customer_reads_it(client, owner, customer):
    made = make(client, owner)

    assert made.status_code == 201
    [seen] = client.get("/products", headers=customer).json()["content"]
    assert (seen["id"], seen["name"], seen["line"], seen["price_minor"], seen["currency"]) == (
        made.json()["id"],
        "ווקס מט",
        "100 מ״ל",
        6500,
        "ILS",
    )
    assert (seen["active"], seen["in_stock"], seen["image_url"]) == (True, True, None)


@pytest.mark.parametrize(
    "fields",
    [{"name": " "}, {"name": "x" * 81}, {"line": "x" * 121}, {"price_minor": -1}, {"price_minor": None}],
)
def test_a_product_needs_a_name_and_a_price_that_is_not_negative(client, owner, fields):
    assert make(client, owner, **fields).status_code == 422


def test_only_the_owner_keeps_the_shelf(client, customer, wax):
    assert make(client, customer).status_code == 403
    assert client.patch(f"/products/{wax}", headers=customer, json={"in_stock": False}).status_code == 403
    assert client.put(f"/products/{wax}/image", headers=customer, json={"data": "eA=="}).status_code == 403
    assert client.get("/products").status_code == 401


def test_a_withdrawn_product_is_the_owners_alone_and_one_out_of_stock_is_still_shown(client, owner, customer):
    gone = make(client, owner, name="נמשך").json()["id"]
    out = make(client, owner, name="אזל").json()["id"]
    client.patch(f"/products/{gone}", headers=owner, json={"active": False})
    client.patch(f"/products/{out}", headers=owner, json={"in_stock": False})

    seen = {p["id"]: p for p in client.get("/products", headers=customer).json()["content"]}

    assert gone not in seen and seen[out]["in_stock"] is False
    assert {gone, out} <= {p["id"] for p in client.get("/products", headers=owner).json()["content"]}


def test_the_owner_changes_a_product_and_what_was_not_sent_stays(client, owner, wax):
    changed = client.patch(f"/products/{wax}", headers=owner, json={"price_minor": 7000}).json()

    assert (changed["name"], changed["line"], changed["price_minor"]) == ("ווקס מט", "100 מ״ל", 7000)
    assert client.patch("/products/prd_nope", headers=owner, json={"price_minor": 1}).status_code == 404


def test_a_products_picture_is_served_and_gone_once_removed(client, owner, customer, wax):
    body = {"data": base64.b64encode(JPEG).decode()}
    url = client.put(f"/products/{wax}/image", headers=owner, json=body).json()["image_url"]

    assert url.startswith("/media/product-") and client.get(url).content == JPEG
    assert client.put(f"/products/{wax}/image", headers=owner, json={"data": "eA=="}).json()["code"] == (
        "invalid_image"
    )
    assert client.delete(f"/products/{wax}/image", headers=owner).json()["image_url"] is None
    assert client.get(url).status_code == 404


def test_a_product_is_kept_for_a_booking_ahead_and_the_booking_names_it(
    client, customer, owner, barber, wax, ahead
):
    kept = keep(client, customer, ahead, wax)

    assert kept.status_code == 200
    assert kept.json()["products"] == [{"id": wax, "name": "ווקס מט"}]
    assert client.get(f"/bookings/{ahead}", headers=customer).json()["products"] == kept.json()["products"]
    diary = client.get("/bookings", headers=owner, params={"barber_id": barber}).json()["content"]
    [in_diary] = [b for b in diary if b["id"] == ahead]
    assert in_diary["products"] == kept.json()["products"]


def test_kept_twice_it_is_kept_once_and_several_keep_their_order(client, customer, owner, wax, ahead):
    shampoo = make(client, owner, name="שמפו").json()["id"]
    keep(client, customer, ahead, wax)
    keep(client, customer, ahead, shampoo)

    again = keep(client, customer, ahead, wax)

    assert again.status_code == 200
    assert [p["id"] for p in again.json()["products"]] == [wax, shampoo]


def test_a_kept_product_is_released_and_releasing_twice_is_no_error(client, customer, wax, ahead):
    keep(client, customer, ahead, wax)

    first = client.delete(f"/bookings/{ahead}/products/{wax}", headers=customer)
    second = client.delete(f"/bookings/{ahead}/products/{wax}", headers=customer)

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["products"] == []


@pytest.mark.parametrize("change", [{"active": False}, {"in_stock": False}])
def test_a_product_withdrawn_or_out_of_stock_cannot_be_kept(client, customer, owner, wax, ahead, change):
    client.patch(f"/products/{wax}", headers=owner, json=change)

    refused = keep(client, customer, ahead, wax)

    assert (refused.status_code, refused.json()["code"]) == (422, "product_unavailable")
    assert client.get(f"/bookings/{ahead}", headers=customer).json()["products"] == []


def test_nothing_is_kept_for_a_booking_that_is_over_or_cancelled(
    client, customer, barber, services, wax, ahead
):
    over = past_booking(client, customer, barber, services[HAIRCUT]["id"])
    client.post(f"/bookings/{ahead}/cancel", headers=customer)

    for booking in (over, ahead):
        refused = keep(client, customer, booking, wax)
        assert (refused.status_code, refused.json()["code"]) == (409, "booking_closed")


def test_somebody_elses_booking_is_not_found_and_a_barber_keeps_nothing(
    client, new_customer, owner, wax, ahead
):
    _, their_barber = a_second_barber(client, owner)

    assert keep(client, new_customer(), ahead, wax).status_code == 404
    assert keep(client, their_barber, ahead, wax).status_code == 403
    assert keep(client, owner, ahead, "prd_nope").status_code == 404
    assert keep(client, owner, ahead, wax).status_code == 200


def test_the_database_refuses_a_negative_price(client):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with client.app.state.sessionmaker() as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO products (id, name, line, price_minor, active, in_stock, created_at)"
                " VALUES ('prd_x', 'x', '', -1, 1, 1, '2026-01-01 00:00:00')"
            )
        )
