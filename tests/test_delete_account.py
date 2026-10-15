"""A customer deletes their own account: what is theirs goes, what the shop needs stays without them."""

from __future__ import annotations

from app.models import OtpCode, PushSubscription, Review, User
from tests.conftest import HAIRCUT, at, book, local_day, login
from tests.test_push import fresh, pushed, shop, subscribe  # noqa: F401 - pushed is a fixture
from tests.test_reviews import past_booking
from tests.test_sign_in_with_code import sign_in


def me_id(client, headers) -> str:
    return client.get("/me", headers=headers).json()["id"]


def test_the_customer_is_emptied_and_closed_and_the_shop_keeps_its_past(
    client, owner, barber, services, texts
):
    me = sign_in(client, texts, phone="0547778888", name="רותם מוחקת")
    haircut = services[HAIRCUT]["id"]
    customer = me_id(client, me)
    over = past_booking(client, me, barber, haircut, hours_ago=30)
    client.post(f"/bookings/{over}/review", headers=me, json={"stars": 5, "text": "מעולה"})
    ahead = book(client, me, barber, haircut, at(local_day(4), "10:00")).json()["id"]
    client.put(f"/customers/{customer}/note", headers=owner, json={"text": "מספר 2"})

    gone = client.delete("/me", headers=me)

    assert gone.status_code == 204
    assert client.get("/me", headers=me).status_code == 401
    seen = {b["id"]: b for b in client.get("/bookings?limit=100", headers=owner).json()["content"]}
    assert seen[ahead]["status"] == "cancelled" and seen[ahead]["cancelled_by"] == "customer"
    assert seen[over]["status"] == "confirmed" and seen[over]["customer_deleted"] is True
    assert seen[over]["customer_name"] is None
    with client.app.state.sessionmaker() as session:
        row = session.get(User, customer)
        assert (row.display_name, row.phone, row.staff_note, row.active) == ("", None, None, False)
        assert row.deleted_at is not None and "רותם" not in row.username
        assert session.query(OtpCode).filter_by(phone="0547778888").count() == 0
        review = session.query(Review).filter_by(booking_id=over).one()
        assert (review.stars, review.text) == (5, "מעולה"), "the customer's review stays"
    assert client.get(f"/customers/{customer}/card", headers=owner).status_code == 404


def test_the_same_phone_opens_a_new_account_afterwards(client, texts):
    first = sign_in(client, texts, phone="0547779999", name="אורי")
    old = me_id(client, first)
    client.delete("/me", headers=first)

    again = sign_in(client, texts, phone="0547779999", name="אורי")

    assert me_id(client, again) != old
    assert client.get("/me", headers=again).json()["display_name"] == "אורי"


def test_only_a_customer_deletes_their_account(client, owner, barber):
    with client.app.state.sessionmaker() as session:
        barber_headers = login(client, session.get(User, barber).username, "long-enough")

    assert client.delete("/me", headers=owner).status_code == 403
    assert client.delete("/me", headers=barber_headers).status_code == 403
    assert client.delete("/me").status_code == 401


def test_the_staff_are_told_of_the_bookings_cancelled_and_the_customer_is_told_nothing_more(
    pushed,  # noqa: F811 - the fixture, imported from tests.test_push
    passwords,
):
    client, fake = pushed
    _, barber, barber_headers, haircut = shop(client, passwords)
    me = fresh(client)
    book(client, me, barber, haircut, at(local_day(3), "10:00"))
    staff = subscribe(client, barber_headers, "barber")
    mine = subscribe(client, me, "me")

    client.delete("/me", headers=me)

    told = client.post("/push/notice", json={"endpoint": staff}).json()
    assert fake.sent == [staff] and told["title"] == "ביטול תור"
    with client.app.state.sessionmaker() as session:
        assert session.query(PushSubscription).filter_by(endpoint=mine).count() == 0


def test_a_password_no_longer_signs_the_customer_in(client):
    me = fresh(client)
    name = client.get("/me", headers=me).json()["username"]
    client.delete("/me", headers=me)

    assert client.post("/auth/token", json={"username": name, "password": "long-enough"}).status_code == 401
