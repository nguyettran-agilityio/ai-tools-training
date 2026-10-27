"""ReservationService.create / cancel: not-found, ownership, and
duplicate/already-closed guards not exercised by
`tests/test_reservation_notify.py` (which focuses on the notify pipeline).
"""

import uuid

from app.core.notifications import InMemoryNotifier, set_notifier


def create_category(client, token, auth_headers, name=None):
    name = name or f"Cat {uuid.uuid4()}"
    response = client.post("/categories", json={"name": name}, headers=auth_headers(token))
    return response.json()["id"]


def create_book(client, admin_token, auth_headers, **overrides):
    category_id = overrides.pop("category_id", None) or create_category(
        client, admin_token, auth_headers
    )
    payload = {
        "title": "Clean Code",
        "author": "Robert C. Martin",
        "isbn": f"isbn-{uuid.uuid4()}",
        "categoryId": category_id,
        "totalCopies": 1,
    }
    payload.update(overrides)
    response = client.post("/books", json=payload, headers=auth_headers(admin_token))
    return response.json()


def borrow(client, token, auth_headers, book_id):
    return client.post("/borrowings", json={"bookId": book_id}, headers=auth_headers(token))


def return_borrowing(client, token, auth_headers, borrowing_id):
    return client.post(f"/borrowings/{borrowing_id}/return", headers=auth_headers(token))


def reserve(client, token, auth_headers, book_id):
    return client.post("/reservations", json={"bookId": book_id}, headers=auth_headers(token))


def cancel(client, token, auth_headers, reservation_id):
    return client.delete(f"/reservations/{reservation_id}", headers=auth_headers(token))


def my_reservation_for_book(client, token, auth_headers, book_id):
    response = client.get("/reservations/my", headers=auth_headers(token))
    items = response.json()["items"]
    return next(r for r in items if r["bookId"] == book_id)


def register_member(client, email, full_name) -> str:
    password = "supersecret"
    payload = {"email": email, "password": password, "fullName": full_name}
    client.post("/auth/register", json=payload)
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


class TestCreateReservation:
    def test_reserving_nonexistent_book_returns_404(self, client, member_token, auth_headers):
        response = reserve(client, member_token, auth_headers, str(uuid.uuid4()))

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_duplicate_reservation_while_pending_returns_409(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers)

        first = reserve(client, member_token, auth_headers, book["id"])
        second = reserve(client, member_token, auth_headers, book["id"])

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.json()["code"] == "CONFLICT"

    def test_duplicate_reservation_while_notified_returns_409(
        self, client, admin_token, member_token, auth_headers
    ):
        """The duplicate guard treats `notified` (not just `pending`) as
        still-open — reproduce that by driving a reservation to `notified`
        via the real return/notify pipeline, then reserving again."""
        set_notifier(InMemoryNotifier())
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        other_member = register_member(client, "other@example.com", "Other Member")
        borrowing = borrow(client, other_member, auth_headers, book["id"]).json()

        assert reserve(client, member_token, auth_headers, book["id"]).status_code == 201
        return_borrowing(client, other_member, auth_headers, borrowing["id"])

        reservation = my_reservation_for_book(client, member_token, auth_headers, book["id"])
        assert reservation["status"] == "notified"

        again = reserve(client, member_token, auth_headers, book["id"])
        assert again.status_code == 409
        assert again.json()["code"] == "CONFLICT"


class TestCancelReservation:
    def test_cancelling_nonexistent_reservation_returns_404(
        self, client, member_token, auth_headers
    ):
        response = cancel(client, member_token, auth_headers, str(uuid.uuid4()))

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_cancelling_another_users_reservation_returns_403(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers)
        owner_reservation = reserve(client, member_token, auth_headers, book["id"]).json()
        other_member = register_member(client, "intruder@example.com", "Intruder")

        response = cancel(client, other_member, auth_headers, owner_reservation["id"])

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_cancelling_already_cancelled_reservation_returns_409(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers)
        reservation = reserve(client, member_token, auth_headers, book["id"]).json()

        first_cancel = cancel(client, member_token, auth_headers, reservation["id"])
        second_cancel = cancel(client, member_token, auth_headers, reservation["id"])

        assert first_cancel.status_code == 204
        assert second_cancel.status_code == 409
        assert second_cancel.json()["code"] == "CONFLICT"
