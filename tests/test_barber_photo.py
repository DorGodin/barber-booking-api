"""A barber's picture: the owner's to give and take away, accepted by its bytes, served to anyone."""

from __future__ import annotations

import base64

from tests.pictures import JPEG


def put(client, headers, barber, raw=JPEG):
    return client.put(
        f"/barbers/{barber}/photo", headers=headers, json={"data": base64.b64encode(raw).decode()}
    )


def test_the_owner_gives_a_barber_a_picture_customers_see_and_anyone_is_served(
    client, owner, customer, barber
):
    url = put(client, owner, barber).json()["photo_url"]

    assert url.startswith("/media/barber-") and client.get(url).content == JPEG
    seen = next(b for b in client.get("/barbers", headers=customer).json()["content"] if b["id"] == barber)
    assert seen["photo_url"] == url


def test_a_picture_replaced_or_taken_away_is_no_longer_served(client, owner, barber):
    first = put(client, owner, barber).json()["photo_url"]
    second = put(client, owner, barber).json()["photo_url"]

    assert client.get(first).status_code == 404 and client.get(second).status_code == 200
    assert client.delete(f"/barbers/{barber}/photo", headers=owner).json()["photo_url"] is None
    assert client.get(second).status_code == 404


def test_only_a_picture_and_only_the_owner(client, owner, customer, barber):
    assert put(client, owner, barber, raw=b"GIF89a" + b"\x00" * 20).json()["code"] == "invalid_image"
    assert put(client, customer, barber).status_code == 403
    assert client.delete(f"/barbers/{barber}/photo", headers=customer).status_code == 403
    assert put(client, owner, "usr_nobody").status_code == 404


def test_a_replaced_or_removed_picture_leaves_no_file_behind(client, owner, barber):
    """Not seen from outside - an unreferenced file is never served - but a shop that changes its
    barbers' pictures would fill its disk."""
    folder = client.app.state.media_dir
    first = put(client, owner, barber).json()["photo_url"].removeprefix("/media/")
    second = put(client, owner, barber).json()["photo_url"].removeprefix("/media/")

    assert not (folder / first).exists() and (folder / second).exists()
    client.delete(f"/barbers/{barber}/photo", headers=owner)
    assert not (folder / second).exists()
