"""Book router/service integration tests, through the real HTTP API."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.modules.book.models import Book
from app.modules.borrowing.models import Borrowing
from app.modules.reservation.models import Reservation
from app.modules.user.models import User


def create_category(client, token, auth_headers, name="Fiction"):
    response = client.post("/categories", json={"name": name}, headers=auth_headers(token))
    return response.json()["id"]


def create_book(client, token, auth_headers, category_id, **overrides):
    payload = {
        "title": "Clean Code",
        "author": "Robert C. Martin",
        "isbn": f"isbn-{uuid.uuid4()}",
        "categoryId": str(category_id),
        "totalCopies": 3,
    }
    payload.update(overrides)
    return client.post("/books", json=payload, headers=auth_headers(token))


class TestCreateBook:
    def test_returns_201_available_copies_equals_total_and_status_available(
        self, client, admin_token, auth_headers
    ):
        category_id = create_category(client, admin_token, auth_headers)

        response = create_book(client, admin_token, auth_headers, category_id, totalCopies=3)

        assert response.status_code == 201
        data = response.json()
        assert data["availableCopies"] == 3
        assert data["totalCopies"] == 3
        assert data["status"] == "available"

    def test_zero_total_copies_returns_status_unavailable(self, client, admin_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)

        response = create_book(client, admin_token, auth_headers, category_id, totalCopies=0)

        assert response.status_code == 201
        data = response.json()
        assert data["availableCopies"] == 0
        assert data["status"] == "unavailable"

    def test_unknown_category_id_returns_404(self, client, admin_token, auth_headers):
        response = create_book(client, admin_token, auth_headers, uuid.uuid4())

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_duplicate_isbn_returns_409_conflict(self, client, admin_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)
        isbn = f"isbn-{uuid.uuid4()}"
        create_book(client, admin_token, auth_headers, category_id, isbn=isbn)

        response = create_book(client, admin_token, auth_headers, category_id, isbn=isbn)

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_as_member_returns_403_forbidden(self, client, admin_token, member_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)

        response = create_book(client, member_token, auth_headers, category_id)

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_anonymous_returns_401_unauthorized(self, client, admin_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)

        response = client.post(
            "/books",
            json={
                "title": "Clean Code",
                "author": "Robert C. Martin",
                "isbn": "isbn-1",
                "categoryId": category_id,
                "totalCopies": 3,
            },
        )

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_missing_title_returns_422(self, client, admin_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)

        response = client.post(
            "/books",
            json={
                "author": "Robert C. Martin",
                "isbn": "isbn-1",
                "categoryId": category_id,
                "totalCopies": 3,
            },
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 422


class TestListBooks:
    def _seed(self, client, admin_token, auth_headers):
        fiction = create_category(client, admin_token, auth_headers, name="Fiction")
        history = create_category(client, admin_token, auth_headers, name="History")

        create_book(
            client,
            admin_token,
            auth_headers,
            fiction,
            title="Clean Code",
            author="Robert C. Martin",
            isbn=f"isbn-{uuid.uuid4()}",
        )
        create_book(
            client,
            admin_token,
            auth_headers,
            fiction,
            title="Clean Architecture",
            author="Robert C. Martin",
            isbn=f"isbn-{uuid.uuid4()}",
        )
        create_book(
            client,
            admin_token,
            auth_headers,
            fiction,
            title="The Hobbit",
            author="J.R.R. Tolkien",
            isbn=f"isbn-{uuid.uuid4()}",
            totalCopies=0,
        )
        create_book(
            client,
            admin_token,
            auth_headers,
            history,
            title="Sapiens",
            author="Yuval Noah Harari",
            isbn=f"isbn-{uuid.uuid4()}",
        )
        create_book(
            client,
            admin_token,
            auth_headers,
            history,
            title="Deep History",
            author="Someone Clean",
            isbn=f"isbn-{uuid.uuid4()}",
            totalCopies=0,
        )
        create_book(
            client,
            admin_token,
            auth_headers,
            history,
            title="Guns, Germs, and Steel",
            author="Jared Diamond",
            isbn=f"isbn-{uuid.uuid4()}",
        )
        return fiction, history

    def test_q_matches_title_case_insensitive(self, client, admin_token, auth_headers):
        self._seed(client, admin_token, auth_headers)

        response = client.get("/books", params={"q": "clean"})

        assert response.status_code == 200
        data = response.json()
        titles = {b["title"] for b in data["items"]}
        assert titles == {"Clean Code", "Clean Architecture", "Deep History"}
        assert data["total"] == 3

    def test_q_matches_author(self, client, admin_token, auth_headers):
        self._seed(client, admin_token, auth_headers)

        response = client.get("/books", params={"q": "tolkien"})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "The Hobbit"

    def test_category_id_filter(self, client, admin_token, auth_headers):
        fiction, _history = self._seed(client, admin_token, auth_headers)

        response = client.get("/books", params={"categoryId": fiction})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3

    def test_available_only_excludes_zero_copies(self, client, admin_token, auth_headers):
        self._seed(client, admin_token, auth_headers)

        response = client.get("/books", params={"availableOnly": True})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 4
        assert all(item["availableCopies"] > 0 for item in data["items"])

    def test_combined_filters(self, client, admin_token, auth_headers):
        _fiction, history = self._seed(client, admin_token, auth_headers)

        response = client.get(
            "/books", params={"q": "clean", "categoryId": history, "availableOnly": True}
        )

        assert response.status_code == 200
        data = response.json()
        # "Deep History" matches "clean" (author "Someone Clean") but has 0 copies.
        assert data["total"] == 0

    def test_pagination_totals(self, client, admin_token, auth_headers):
        self._seed(client, admin_token, auth_headers)

        response = client.get("/books", params={"page": 1, "pageSize": 4})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 6
        assert data["totalPages"] == 2
        assert len(data["items"]) == 4


class TestUpdateBook:
    def test_partial_patch_keeps_other_fields(self, client, admin_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)
        created = create_book(client, admin_token, auth_headers, category_id).json()

        response = client.patch(
            f"/books/{created['id']}",
            json={"description": "A classic"},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "A classic"
        assert data["title"] == created["title"]
        assert data["isbn"] == created["isbn"]
        assert data["totalCopies"] == created["totalCopies"]

    def test_raising_total_copies_with_one_borrowed_updates_available(
        self, client, admin_token, auth_headers, db_engine
    ):
        category_id = create_category(client, admin_token, auth_headers)
        created = create_book(client, admin_token, auth_headers, category_id, totalCopies=3).json()
        book_id = uuid.UUID(created["id"])

        with Session(db_engine) as session:
            member = session.exec(select(User)).first()
            assert member is not None
            book = session.get(Book, book_id)
            assert book is not None
            book.available_copies = 2  # 1 copy currently borrowed
            session.add(book)
            session.add(
                Borrowing(
                    user_id=member.id,
                    book_id=book_id,
                    borrowed_at=datetime.now(UTC),
                    due_date=datetime.now(UTC) + timedelta(days=14),
                    returned_at=None,
                )
            )
            session.commit()

        response = client.patch(
            f"/books/{created['id']}",
            json={"totalCopies": 5},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["totalCopies"] == 5
        assert data["availableCopies"] == 4

    def test_lowering_total_copies_below_borrowed_returns_400(
        self, client, admin_token, auth_headers, db_engine
    ):
        category_id = create_category(client, admin_token, auth_headers)
        created = create_book(client, admin_token, auth_headers, category_id, totalCopies=3).json()
        book_id = uuid.UUID(created["id"])

        with Session(db_engine) as session:
            book = session.get(Book, book_id)
            assert book is not None
            book.available_copies = 0  # all 3 copies currently borrowed
            session.add(book)
            session.commit()

        response = client.patch(
            f"/books/{created['id']}",
            json={"totalCopies": 2},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "BAD_REQUEST"

    def test_change_isbn_to_existing_one_returns_409(self, client, admin_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)
        taken_isbn = f"isbn-{uuid.uuid4()}"
        create_book(client, admin_token, auth_headers, category_id, isbn=taken_isbn)
        created = create_book(client, admin_token, auth_headers, category_id).json()

        response = client.patch(
            f"/books/{created['id']}",
            json={"isbn": taken_isbn},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"


class TestDeleteBook:
    def test_no_active_borrowings_returns_204_then_404(self, client, admin_token, auth_headers):
        category_id = create_category(client, admin_token, auth_headers)
        created = create_book(client, admin_token, auth_headers, category_id).json()

        response = client.delete(f"/books/{created['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 204
        assert response.content == b""

        follow_up = client.get(f"/books/{created['id']}")
        assert follow_up.status_code == 404

    def test_active_borrowing_returns_409_conflict(
        self, client, admin_token, auth_headers, db_engine
    ):
        category_id = create_category(client, admin_token, auth_headers)
        created = create_book(client, admin_token, auth_headers, category_id).json()
        book_id = uuid.UUID(created["id"])

        with Session(db_engine) as session:
            member = session.exec(select(User)).first()
            assert member is not None
            session.add(
                Borrowing(
                    user_id=member.id,
                    book_id=book_id,
                    borrowed_at=datetime.now(UTC),
                    due_date=datetime.now(UTC) + timedelta(days=14),
                    returned_at=None,
                )
            )
            session.commit()

        response = client.delete(f"/books/{created['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_only_returned_borrowing_does_not_block_delete(
        self, client, admin_token, auth_headers, db_engine
    ):
        category_id = create_category(client, admin_token, auth_headers)
        created = create_book(client, admin_token, auth_headers, category_id).json()
        book_id = uuid.UUID(created["id"])

        with Session(db_engine) as session:
            member = session.exec(select(User)).first()
            assert member is not None
            borrowed_at = datetime.now(UTC) - timedelta(days=20)
            session.add(
                Borrowing(
                    user_id=member.id,
                    book_id=book_id,
                    borrowed_at=borrowed_at,
                    due_date=borrowed_at + timedelta(days=14),
                    returned_at=datetime.now(UTC),
                )
            )
            session.commit()

        response = client.delete(f"/books/{created['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 204

    def test_open_reservation_returns_409_conflict(
        self, client, admin_token, auth_headers, db_engine
    ):
        category_id = create_category(client, admin_token, auth_headers)
        created = create_book(client, admin_token, auth_headers, category_id).json()
        book_id = uuid.UUID(created["id"])

        with Session(db_engine) as session:
            member = session.exec(select(User)).first()
            assert member is not None
            session.add(Reservation(user_id=member.id, book_id=book_id))
            session.commit()

        response = client.delete(f"/books/{created['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"
