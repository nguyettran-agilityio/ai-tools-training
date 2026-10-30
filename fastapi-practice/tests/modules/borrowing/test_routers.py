"""Borrowing router/service integration tests, through the real HTTP API."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.borrowing.mappers import to_borrowing_read
from app.modules.borrowing.models import Borrowing, BorrowingBan
from app.modules.borrowing.repositories_sqlmodel import BorrowingRepository


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


@pytest.fixture
def second_member_token(client) -> str:
    """A second, distinct member (`member_token` from `conftest.py` is the
    first) so tests can exercise "someone else's borrowing"."""
    email = "member2@example.com"
    password = "supersecret"
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "fullName": "Second Member"},
    )
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


class TestBorrowBook:
    def test_happy_path_returns_201_active_status_and_due_date_14_days_out(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)

        response = borrow(client, member_token, auth_headers, book["id"])

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "active"
        assert data["returnedAt"] is None
        assert data["bookId"] == book["id"]

        borrowed_at = datetime.fromisoformat(data["borrowedAt"])
        due_date = datetime.fromisoformat(data["dueDate"])
        assert due_date == borrowed_at + timedelta(days=14)

        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 0

    def test_unknown_book_returns_404(self, client, member_token, auth_headers):
        response = borrow(client, member_token, auth_headers, str(uuid.uuid4()))

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_anonymous_returns_401(self, client, admin_token, auth_headers):
        book = create_book(client, admin_token, auth_headers)

        response = client.post("/borrowings", json={"bookId": book["id"]})

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_zero_available_copies_auto_reserves_then_succeeds_after_a_return(
        self, client, admin_token, member_token, second_member_token, auth_headers
    ):
        """Borrowing an out-of-stock book is no longer a hard 409 — it's the
        race-condition safety net: the caller is auto-queued instead. See
        `tests/test_borrow_auto_reserve.py` for the dedicated coverage of
        that behavior; this test just confirms the older "then succeeds
        after a return" flow still ends the same way once the book is free
        again."""
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        first = borrow(client, member_token, auth_headers, book["id"])
        assert first.status_code == 201

        queued = borrow(client, second_member_token, auth_headers, book["id"])
        assert queued.status_code == 202
        assert queued.json()["status"] == "pending"

        return_borrowing(client, member_token, auth_headers, first.json()["id"])

        retried = borrow(client, second_member_token, auth_headers, book["id"])
        assert retried.status_code == 201

    def test_same_member_same_book_twice_returns_409(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=5)
        borrow(client, member_token, auth_headers, book["id"])

        response = borrow(client, member_token, auth_headers, book["id"])

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_sixth_distinct_book_returns_409_then_succeeds_after_a_return(
        self, client, admin_token, member_token, auth_headers
    ):
        books = [create_book(client, admin_token, auth_headers, totalCopies=1) for _ in range(6)]

        borrowed_ids = []
        for book in books[:5]:
            response = borrow(client, member_token, auth_headers, book["id"])
            assert response.status_code == 201
            borrowed_ids.append(response.json()["id"])

        sixth = borrow(client, member_token, auth_headers, books[5]["id"])
        assert sixth.status_code == 409
        assert "borrow limit" in sixth.json()["message"].lower()

        return_borrowing(client, member_token, auth_headers, borrowed_ids[0])

        retried = borrow(client, member_token, auth_headers, books[5]["id"])
        assert retried.status_code == 201


class TestReturnBook:
    def test_happy_path_returns_200_returned_status_and_restores_copies(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        created = borrow(client, member_token, auth_headers, book["id"]).json()

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "returned"
        assert data["returnedAt"] is not None

        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 1

    def test_returning_twice_returns_409(self, client, admin_token, member_token, auth_headers):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        created = borrow(client, member_token, auth_headers, book["id"]).json()
        return_borrowing(client, member_token, auth_headers, created["id"])

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_returning_someone_elses_borrowing_returns_403(
        self, client, admin_token, member_token, second_member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        created = borrow(client, member_token, auth_headers, book["id"]).json()

        response = return_borrowing(client, second_member_token, auth_headers, created["id"])

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_unknown_borrowing_id_returns_404(self, client, member_token, auth_headers):
        response = return_borrowing(client, member_token, auth_headers, str(uuid.uuid4()))

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


class TestLateReturnBan:
    """Router side of #40: the ban is checked in the `borrowing_ban` table,
    since no endpoint exposes it yet (#41/#43)."""

    @staticmethod
    def _borrow_late(client, admin_token, member_token, auth_headers, db_engine, **book):
        """Borrow through the API, then move `due_date` into the past."""
        created_book = create_book(client, admin_token, auth_headers, **book)
        created = borrow(client, member_token, auth_headers, created_book["id"]).json()
        with Session(db_engine) as session:
            row = session.get(Borrowing, uuid.UUID(created["id"]))
            assert row is not None
            row.due_date = datetime.now(UTC) - timedelta(days=1)
            session.add(row)
            session.commit()
        return created_book, created

    @staticmethod
    def _ban_for(db_engine, user_id: str) -> BorrowingBan | None:
        with Session(db_engine) as session:
            return session.get(BorrowingBan, uuid.UUID(user_id))

    def test_late_return_returns_200_and_bans_the_member(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        book, created = self._borrow_late(
            client, admin_token, member_token, auth_headers, db_engine, totalCopies=2
        )

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "returned"
        assert not any("ban" in key.lower() for key in data)
        assert client.get(f"/books/{book['id']}").json()["availableCopies"] == 2

        ban = self._ban_for(db_engine, created["userId"])
        assert ban is not None
        returned_at = datetime.fromisoformat(data["returnedAt"])
        assert ban.banned_until.replace(tzinfo=UTC) == returned_at + timedelta(days=7)
        assert ban.source_borrowing_id == uuid.UUID(created["id"])

    def test_on_time_return_returns_200_and_creates_no_ban(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        book = create_book(client, admin_token, auth_headers)
        created = borrow(client, member_token, auth_headers, book["id"]).json()

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 200
        assert self._ban_for(db_engine, created["userId"]) is None

    def test_someone_elses_late_loan_returns_403_and_creates_no_ban(
        self, client, admin_token, member_token, second_member_token, auth_headers, db_engine
    ):
        _, created = self._borrow_late(client, admin_token, member_token, auth_headers, db_engine)
        other_id = client.get("/auth/me", headers=auth_headers(second_member_token)).json()["id"]

        response = return_borrowing(client, second_member_token, auth_headers, created["id"])

        assert response.status_code == 403
        assert response.json() == {
            "code": "FORBIDDEN",
            "message": "You can only return your own borrowings",
            "errors": None,
        }
        assert self._ban_for(db_engine, created["userId"]) is None
        assert self._ban_for(db_engine, other_id) is None

    def test_admin_returning_a_members_late_loan_returns_403_and_creates_no_ban(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        _, created = self._borrow_late(client, admin_token, member_token, auth_headers, db_engine)

        response = return_borrowing(client, admin_token, auth_headers, created["id"])

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"
        assert self._ban_for(db_engine, created["userId"]) is None

    def test_returning_a_late_loan_twice_returns_409_and_keeps_the_ban(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        _, created = self._borrow_late(client, admin_token, member_token, auth_headers, db_engine)
        return_borrowing(client, member_token, auth_headers, created["id"])
        before = self._ban_for(db_engine, created["userId"])
        assert before is not None

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 409
        assert response.json() == {
            "code": "CONFLICT",
            "message": "Book already returned",
            "errors": None,
        }
        after = self._ban_for(db_engine, created["userId"])
        assert after is not None
        assert after.banned_until == before.banned_until

    def test_late_return_still_notifies_pending_reservers_returns_200(
        self, client, admin_token, member_token, second_member_token, auth_headers, db_engine
    ):
        book, created = self._borrow_late(
            client, admin_token, member_token, auth_headers, db_engine, totalCopies=1
        )
        reserved = client.post(
            "/reservations", json={"bookId": book["id"]}, headers=auth_headers(second_member_token)
        )
        assert reserved.status_code == 201

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 200
        items = client.get("/reservations/my", headers=auth_headers(second_member_token)).json()[
            "items"
        ]
        [reservation] = [r for r in items if r["bookId"] == book["id"]]
        assert reservation["status"] == "notified"

    def test_late_return_recorded_before_deploy_does_not_ban_returns_201(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """No backfill: a late return already in the DB (not made through
        `return_book`) never creates a ban, and the member can still borrow."""
        old_book = create_book(client, admin_token, auth_headers)
        me = client.get("/auth/me", headers=auth_headers(member_token)).json()
        borrowed_at = datetime.now(UTC) - timedelta(days=30)
        with Session(db_engine) as session:
            session.add(
                Borrowing(
                    user_id=uuid.UUID(me["id"]),
                    book_id=uuid.UUID(old_book["id"]),
                    borrowed_at=borrowed_at,
                    due_date=borrowed_at + timedelta(days=14),
                    returned_at=borrowed_at + timedelta(days=20),
                )
            )
            session.commit()
        new_book = create_book(client, admin_token, auth_headers)

        response = borrow(client, member_token, auth_headers, new_book["id"])

        assert response.status_code == 201
        assert self._ban_for(db_engine, me["id"]) is None


class TestOverdueVisibility:
    def test_past_due_date_computes_overdue_status(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """Minimal check that an unreturned, past-due `Borrowing` reads back
        as "overdue" — full `/borrowings/overdue` listing is a later task."""
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        me = client.get("/auth/me", headers=auth_headers(member_token)).json()

        borrowed_at = datetime.now(UTC) - timedelta(days=20)
        with Session(db_engine) as session:
            session.add(
                Borrowing(
                    user_id=uuid.UUID(me["id"]),
                    book_id=uuid.UUID(book["id"]),
                    borrowed_at=borrowed_at,
                    due_date=borrowed_at + timedelta(days=14),
                    returned_at=None,
                )
            )
            session.commit()

        with Session(db_engine) as session:
            repo = BorrowingRepository(SQLModelBackend(session, Borrowing, to_borrowing_read))
            [result] = repo.list_active_by_user(uuid.UUID(me["id"]))

        assert result.status == "overdue"


class TestAtomicity:
    def test_failed_borrowing_insert_rolls_back_the_book_decrement(
        self, client, admin_token, member_token, auth_headers, monkeypatch
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)

        def _raise(self, data):
            raise RuntimeError("simulated failure after the book decrement")

        monkeypatch.setattr(BorrowingRepository, "create", _raise)

        with pytest.raises(RuntimeError):
            borrow(client, member_token, auth_headers, book["id"])

        # `TestClient` re-raises server exceptions by default, so the
        # request above never got to send a response — check the DB state
        # directly instead of via a second HTTP call.
        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 1


class TestReports:
    """`GET /borrowings/reports/overdue` and `/reports/late-returns` (#42)."""

    REPORT_URLS = ("/borrowings/reports/overdue", "/borrowings/reports/late-returns")

    def _member_id(self, client, member_token, auth_headers) -> uuid.UUID:
        me = client.get("/auth/me", headers=auth_headers(member_token)).json()
        return uuid.UUID(me["id"])

    def _add_borrowing(
        self,
        db_engine,
        user_id: uuid.UUID,
        book_id: str,
        *,
        due_date: datetime,
        returned_at: datetime | None = None,
        borrowed_at: datetime | None = None,
    ) -> uuid.UUID:
        with Session(db_engine) as session:
            borrowing = Borrowing(
                user_id=user_id,
                book_id=uuid.UUID(book_id),
                borrowed_at=borrowed_at or due_date - timedelta(days=14),
                due_date=due_date,
                returned_at=returned_at,
            )
            session.add(borrowing)
            session.commit()
            return borrowing.id

    def _add_late_return(self, db_engine, user_id, book_id, returned_at: datetime) -> uuid.UUID:
        return self._add_borrowing(
            db_engine,
            user_id,
            book_id,
            due_date=returned_at - timedelta(days=1),
            returned_at=returned_at,
        )

    def _late_returns(self, client, admin_token, auth_headers, **params):
        return client.get(
            "/borrowings/reports/late-returns", params=params, headers=auth_headers(admin_token)
        )

    def test_overdue_report_rows_order_and_utc_z_datetimes(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """TC-42-01, plus every datetime serialized with `Z`, not `+00:00`."""
        book = create_book(client, admin_token, auth_headers, title="Overdue Book")
        member_id = self._member_id(client, member_token, auth_headers)
        now = datetime.now(UTC)
        older = self._add_borrowing(
            db_engine, member_id, book["id"], due_date=now - timedelta(days=5)
        )
        newer = self._add_borrowing(
            db_engine, member_id, book["id"], due_date=now - timedelta(days=1)
        )
        self._add_borrowing(db_engine, member_id, book["id"], due_date=now + timedelta(days=3))
        self._add_borrowing(
            db_engine,
            member_id,
            book["id"],
            due_date=now - timedelta(days=4),
            returned_at=now - timedelta(days=2),
        )

        response = client.get(
            "/borrowings/reports/overdue?page=1&pageSize=20", headers=auth_headers(admin_token)
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items", "total", "page", "pageSize", "totalPages"}
        assert body["total"] == 2
        assert [row["id"] for row in body["items"]] == [str(newer), str(older)]
        row = body["items"][0]
        assert row["userEmail"] == "member@example.com"
        assert row["bookTitle"] == "Overdue Book"
        assert row["status"] == "overdue"
        assert row["userId"] == str(member_id)
        assert row["bookId"] == book["id"]
        assert row["returnedAt"] is None
        for field in ("borrowedAt", "dueDate"):
            assert row[field].endswith("Z"), row[field]
            assert "+00:00" not in row[field]

    def test_overdue_report_pages_do_not_overlap(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """TC-42-02."""
        book = create_book(client, admin_token, auth_headers)
        member_id = self._member_id(client, member_token, auth_headers)
        now = datetime.now(UTC)
        for days in (1, 2, 3):
            self._add_borrowing(
                db_engine, member_id, book["id"], due_date=now - timedelta(days=days)
            )

        headers = auth_headers(admin_token)
        page1 = client.get("/borrowings/reports/overdue?page=1&pageSize=2", headers=headers)
        page2 = client.get("/borrowings/reports/overdue?page=2&pageSize=2", headers=headers)

        assert page1.json()["total"] == 3
        assert page2.json()["total"] == 3
        ids1 = {row["id"] for row in page1.json()["items"]}
        ids2 = {row["id"] for row in page2.json()["items"]}
        assert len(ids1) == 2
        assert len(ids2) == 1
        assert ids1.isdisjoint(ids2)

    def test_late_returns_contents_order_and_utc_z_datetimes(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """TC-42-03 (exactly-at-due-date is covered in the repository test)."""
        book = create_book(client, admin_token, auth_headers, title="Late Book")
        member_id = self._member_id(client, member_token, auth_headers)
        first = self._add_late_return(
            db_engine, member_id, book["id"], datetime(2026, 11, 1, 8, tzinfo=UTC)
        )
        second = self._add_late_return(
            db_engine, member_id, book["id"], datetime(2026, 11, 2, 8, tzinfo=UTC)
        )
        due_date = datetime(2026, 11, 3, tzinfo=UTC)
        self._add_borrowing(
            db_engine,
            member_id,
            book["id"],
            due_date=due_date,
            returned_at=due_date - timedelta(hours=1),
        )

        response = self._late_returns(client, admin_token, auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert [row["id"] for row in body["items"]] == [str(second), str(first)]
        row = body["items"][0]
        assert row["userEmail"] == "member@example.com"
        assert row["bookTitle"] == "Late Book"
        assert row["status"] == "returned"
        assert row["returnedAt"] == "2026-11-02T08:00:00Z"
        for field in ("borrowedAt", "dueDate", "returnedAt"):
            assert row[field].endswith("Z"), row[field]
            assert "+00:00" not in row[field]

    def test_late_returns_bounds(self, client, admin_token, member_token, auth_headers, db_engine):
        """TC-42-04 / 05 / 06 and Q-42-4 through the real SQLite comparison."""
        book = create_book(client, admin_token, auth_headers)
        member_id = self._member_id(client, member_token, auth_headers)
        t1, t2, t3 = (datetime(2026, 11, day, tzinfo=UTC) for day in (1, 2, 3))
        ids = {
            t: str(self._add_late_return(db_engine, member_id, book["id"], t)) for t in (t1, t2, t3)
        }

        def found(**params) -> set[str]:
            response = self._late_returns(client, admin_token, auth_headers, **params)
            assert response.status_code == 200, response.json()
            return {row["id"] for row in response.json()["items"]}

        # Inclusive on both ends.
        assert found(**{"from": "2026-11-01T00:00:00Z", "to": "2026-11-03T00:00:00Z"}) == set(
            ids.values()
        )
        assert found(**{"from": "2026-11-02T00:00:00Z", "to": "2026-11-02T00:00:00Z"}) == {ids[t2]}
        # Single bound.
        assert found(**{"from": "2026-11-02T00:00:00Z"}) == {ids[t2], ids[t3]}
        assert found(to="2026-11-02T00:00:00Z") == {ids[t1], ids[t2]}
        # No timezone = UTC.
        assert found(**{"from": "2026-11-03T00:00:00"}) == {ids[t3]}
        # Non-UTC offset is converted: 07:00+07:00 == 00:00Z.
        assert found(**{"from": "2026-11-03T07:00:00+07:00"}) == {ids[t3]}
        assert found(to="2026-11-01T07:00:00+07:00") == {ids[t1]}

    def _add_late_returns(
        self, client, admin_token, member_token, auth_headers, db_engine, *returned_at: datetime
    ) -> dict[datetime, str]:
        book = create_book(client, admin_token, auth_headers)
        member_id = self._member_id(client, member_token, auth_headers)
        return {
            t: str(self._add_late_return(db_engine, member_id, book["id"], t)) for t in returned_at
        }

    def _found_ids(self, client, admin_token, auth_headers, **params) -> set[str]:
        response = self._late_returns(client, admin_token, auth_headers, **params)
        assert response.status_code == 200, response.json()
        return {row["id"] for row in response.json()["items"]}

    def test_date_only_to_covers_the_whole_utc_day(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """TC-42-15 (B-42-2): `to=YYYY-MM-DD` = end of that day UTC."""
        start = datetime(2026, 11, 1, tzinfo=UTC)
        last = datetime(2026, 11, 1, 23, 59, 59, 999999, tzinfo=UTC)
        next_midnight = datetime(2026, 11, 2, tzinfo=UTC)
        ids = self._add_late_returns(
            client, admin_token, member_token, auth_headers, db_engine, start, last, next_midnight
        )

        found = self._found_ids(client, admin_token, auth_headers, to="2026-11-01")

        assert found == {ids[start], ids[last]}

    @pytest.mark.parametrize("to", ["2026-11-01T00:00:00Z", "2026-11-01T00:00:00"])
    def test_to_with_a_time_part_keeps_its_literal_meaning(
        self, client, admin_token, member_token, auth_headers, db_engine, to
    ):
        """TC-42-16 (B-42-2)."""
        midnight = datetime(2026, 11, 1, tzinfo=UTC)
        morning = datetime(2026, 11, 1, 10, tzinfo=UTC)
        ids = self._add_late_returns(
            client, admin_token, member_token, auth_headers, db_engine, midnight, morning
        )

        assert self._found_ids(client, admin_token, auth_headers, to=to) == {ids[midnight]}

    def test_date_only_from_and_to_on_the_same_day(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """TC-42-17 (B-42-2)."""
        day_before = datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)
        noon = datetime(2026, 11, 1, 12, tzinfo=UTC)
        next_midnight = datetime(2026, 11, 2, tzinfo=UTC)
        ids = self._add_late_returns(
            client,
            admin_token,
            member_token,
            auth_headers,
            db_engine,
            day_before,
            noon,
            next_midnight,
        )

        found = self._found_ids(
            client, admin_token, auth_headers, **{"from": "2026-11-01", "to": "2026-11-01"}
        )

        assert found == {ids[noon]}

    def test_from_later_the_same_day_as_date_only_to_is_valid(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """TC-42-18 (B-42-2): `from > to` is checked against the end of the
        date-only `to`, so this is 200, not 400."""
        morning = datetime(2026, 11, 1, 10, tzinfo=UTC)
        evening = datetime(2026, 11, 1, 18, tzinfo=UTC)
        ids = self._add_late_returns(
            client, admin_token, member_token, auth_headers, db_engine, morning, evening
        )

        found = self._found_ids(
            client,
            admin_token,
            auth_headers,
            **{"from": "2026-11-01T12:00:00Z", "to": "2026-11-01"},
        )

        assert found == {ids[evening]}

    def test_from_after_to_returns_400(self, client, admin_token, auth_headers):
        """TC-42-07."""
        response = self._late_returns(
            client,
            admin_token,
            auth_headers,
            **{"from": "2026-11-02T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
        )

        assert response.status_code == 400
        assert response.json() == {
            "code": "BAD_REQUEST",
            "message": "'from' must be before 'to'",
            "errors": None,
        }

    @pytest.mark.parametrize("param", ["from", "to"])
    def test_invalid_datetime_returns_422(self, client, admin_token, auth_headers, param):
        """TC-42-08 and Q-42-3."""
        response = self._late_returns(client, admin_token, auth_headers, **{param: "not-a-date"})

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("url", REPORT_URLS)
    @pytest.mark.parametrize("query", ["page=0", "pageSize=0", "pageSize=101", "page=abc"])
    def test_invalid_pagination_returns_422(self, client, admin_token, auth_headers, url, query):
        """Q-42-5."""
        response = client.get(f"{url}?{query}", headers=auth_headers(admin_token))

        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("url", REPORT_URLS)
    def test_no_token_returns_401(self, client, url):
        """TC-42-09."""
        assert client.get(url).status_code == 401

    @pytest.mark.parametrize("url", REPORT_URLS)
    def test_member_token_returns_403(self, client, member_token, auth_headers, url):
        """TC-42-10."""
        assert client.get(url, headers=auth_headers(member_token)).status_code == 403

    @pytest.mark.parametrize("url", REPORT_URLS)
    def test_routes_are_not_shadowed_by_borrowing_id(self, client, admin_token, auth_headers, url):
        """TC-42-12: an empty page, not a `/{borrowing_id}` 404/422."""
        response = client.get(url, headers=auth_headers(admin_token))

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "total": 0,
            "page": 1,
            "pageSize": 10,
            "totalPages": 0,
        }

    def test_existing_overdue_endpoints_are_unchanged(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """TC-42-13: still plain `BorrowingRead` rows, no report fields."""
        book = create_book(client, admin_token, auth_headers)
        member_id = self._member_id(client, member_token, auth_headers)
        self._add_borrowing(
            db_engine, member_id, book["id"], due_date=datetime.now(UTC) - timedelta(days=1)
        )
        headers = auth_headers(admin_token)

        for url in ("/borrowings/overdue", "/borrowings?overdueOnly=true"):
            response = client.get(url, headers=headers)
            assert response.status_code == 200
            [row] = response.json()["items"]
            assert set(row) == {
                "id",
                "userId",
                "bookId",
                "borrowedAt",
                "dueDate",
                "returnedAt",
                "renewedAt",
                "status",
            }

    def test_openapi_declares_report_response_model(self, client):
        """TC-42-14."""
        paths = client.get("/openapi.json").json()["paths"]

        for url in self.REPORT_URLS:
            schema = paths[url]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("Page_BorrowingReportRow_")
