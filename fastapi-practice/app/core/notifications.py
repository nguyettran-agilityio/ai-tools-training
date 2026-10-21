# Standard library
import abc
import asyncio
import logging
import smtplib
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage

# Local application
# core
from app.core.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

# Notification type identifiers (`Notification.type`), so call sites don't
# repeat a raw string. Tests compare against the string literals on purpose:
# changing a value breaks clients.
BOOK_AVAILABLE = "BOOK_AVAILABLE"
OVERDUE_REMINDER = "OVERDUE_REMINDER"


@dataclass(frozen=True)
class Notification:
    user_id: uuid.UUID
    type: str
    book_id: uuid.UUID
    message: str
    # Optional and resolved by the caller, not this module — only
    # `EmailNotifier` reads it. The service already loops per-recipient and
    # has a `UserRepositoryInterface` on hand (see
    # `ReservationService.notify_book_available` /
    # `BorrowingService.notify_overdue`), so resolving `user_id -> email`
    # there keeps this file DB-free. `None` means "no resolvable address" —
    # `EmailNotifier` treats that as a silent skip, not an error.
    email: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_payload(self) -> dict:
        """camelCase payload for the wire; UUID/datetime stringified for json.dumps."""
        return {
            "type": self.type,
            "bookId": str(self.book_id),
            "message": self.message,
            "createdAt": self.created_at.isoformat(),
        }


class Notifier(abc.ABC):
    @abc.abstractmethod
    async def notify(self, notification: Notification) -> None: ...


class InMemoryNotifier(Notifier):
    """Stores sent notifications per recipient — the sink tests read from.
    Call `reset()` between tests; `get_notifier()` is a process-wide singleton."""

    def __init__(self) -> None:
        self._sent: dict[uuid.UUID, list[Notification]] = defaultdict(list)

    async def notify(self, notification: Notification) -> None:
        self._sent[notification.user_id].append(notification)

    def sent_to(self, user_id: uuid.UUID) -> list[Notification]:
        """Test helper: every notification sent to one user, oldest first."""
        return list(self._sent[user_id])

    def reset(self) -> None:
        self._sent.clear()


class WebSocketNotifier(Notifier):
    """Pushes to the recipient's live socket(s) via `ConnectionManager`;
    a no-op when none are open."""

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    async def notify(self, notification: Notification) -> None:
        await self._manager.send_to_user(notification.user_id, notification.to_payload())


class EmailSender(abc.ABC):
    """Low-level "send one email" transport — `EmailNotifier`'s collaborator,
    same relationship `WebSocketNotifier` has with `ConnectionManager`."""

    @abc.abstractmethod
    async def send(self, to: str, subject: str, body: str) -> None: ...


class InMemoryEmailSender(EmailSender):
    """Records 'sent' emails instead of touching SMTP — the default until
    SMTP settings are configured, and the sink tests read from."""

    def __init__(self) -> None:
        self._sent: list[dict[str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        logger.info("Email (in-memory, no SMTP configured) -> %s: %s", to, subject)
        self._sent.append({"to": to, "subject": subject, "body": body})

    def sent_to(self, to: str) -> list[dict[str, str]]:
        """Test helper: every email sent to one address, oldest first."""
        return [email for email in self._sent if email["to"] == to]

    def reset(self) -> None:
        self._sent.clear()


class SMTPEmailSender(EmailSender):
    """Real email delivery via stdlib `smtplib`, run off the event loop
    via `asyncio.to_thread` since `smtplib` is blocking."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        from_address: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address
        # Real providers (Gmail, SendGrid, ...) require STARTTLS on 587, but
        # local catchers used to verify this locally (Mailpit, MailHog, ...)
        # don't advertise it by default — calling `starttls()` against one
        # raises `SMTPNotSupportedError`. Toggle via `SMTP_USE_TLS=false`.
        self._use_tls = use_tls

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            if self._use_tls:
                smtp.starttls()
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(message)
            logger.info("Email (SMTP) -> %s: %s", to, subject)


class EmailNotifier(Notifier):
    """Delivers via an injected `EmailSender`. DB-free by design — reads only
    `Notification.email`, since this singleton can't safely borrow a
    request-scoped DB session."""

    def __init__(self, email_sender: EmailSender) -> None:
        self._email_sender = email_sender

    async def notify(self, notification: Notification) -> None:
        if notification.email is None:
            # No resolvable address (deleted user, lookup failed, ...) —
            # best-effort, not fatal.
            return
        await self._email_sender.send(
            to=notification.email,
            subject=notification.type.replace("_", " ").title(),
            body=notification.message,
        )


class CompositeNotifier(Notifier):
    """Fans one notification out to every channel it wraps (WebSocket, Email, ...).
    Channels are independent — one failing is logged, not propagated."""

    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self._notifiers = notifiers

    async def notify(self, notification: Notification) -> None:
        results = await asyncio.gather(
            *(notifier.notify(notification) for notifier in self._notifiers),
            return_exceptions=True,
        )
        for notifier, result in zip(self._notifiers, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "%s failed to deliver notification to user %s: %s",
                    type(notifier).__name__,
                    notification.user_id,
                    result,
                )


_notifier: Notifier = InMemoryNotifier()


def get_notifier() -> Notifier:
    """Module-level singleton getter — see `set_notifier`."""
    return _notifier


def set_notifier(notifier: Notifier) -> None:
    """Swap the process-wide notifier. Called once by `main.py`'s `lifespan`
    at startup, and by tests to rebind their own notifier."""
    global _notifier
    _notifier = notifier
