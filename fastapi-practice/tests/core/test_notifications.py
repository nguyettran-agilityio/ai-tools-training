"""Unit tests for `EmailNotifier` and `CompositeNotifier` — no database, no
session, no `TestClient`. Compare with `tests/test_reservation_notify.py` /
`tests/test_overdue_notify.py`, which exercise `InMemoryNotifier` end-to-end
through the real HTTP API instead.
"""

# Standard library
import asyncio
import uuid
from unittest.mock import MagicMock, patch

# Local application
from app.core.notifications import (
    CompositeNotifier,
    EmailNotifier,
    InMemoryEmailSender,
    InMemoryNotifier,
    Notification,
    Notifier,
    SMTPEmailSender,
)


def _make_notification(**overrides) -> Notification:
    defaults = {
        "user_id": uuid.uuid4(),
        "type": "BOOK_AVAILABLE",
        "book_id": uuid.uuid4(),
        "message": "A book you reserved is now available.",
    }
    defaults.update(overrides)
    return Notification(**defaults)


class TestEmailNotifier:
    def test_sends_when_email_is_present(self):
        sender = InMemoryEmailSender()
        notifier = EmailNotifier(sender)
        notification = _make_notification(email="member@example.com")

        asyncio.run(notifier.notify(notification))

        sent = sender.sent_to("member@example.com")
        assert len(sent) == 1
        assert sent[0]["subject"] == "Book Available"
        assert sent[0]["body"] == notification.message

    def test_skips_silently_when_email_is_none(self):
        """A deleted user / failed lookup must not raise — see
        `Notification.email`'s docstring."""
        sender = InMemoryEmailSender()
        notifier = EmailNotifier(sender)
        notification = _make_notification(email=None)

        asyncio.run(notifier.notify(notification))

        assert sender.sent_to("member@example.com") == []


class TestSMTPEmailSender:
    """`smtplib.SMTP` is mocked out — these check *what* `SMTPEmailSender`
    does with it (starttls/login/send_message calls), not a real network
    round-trip. See `docs`/`.env.example` for verifying against a real
    catcher (Mailpit) instead."""

    def _make_smtp_mock(self):
        smtp_instance = MagicMock()
        smtp_cls = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp_instance
        return smtp_cls, smtp_instance

    def test_starttls_and_login_when_configured(self):
        smtp_cls, smtp_instance = self._make_smtp_mock()
        sender = SMTPEmailSender(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            from_address="noreply@example.com",
            use_tls=True,
        )

        with patch("app.core.notifications.smtplib.SMTP", smtp_cls):
            asyncio.run(sender.send("member@example.com", "Subject", "Body"))

        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
        smtp_instance.starttls.assert_called_once()
        smtp_instance.login.assert_called_once_with("user", "pass")
        sent_message = smtp_instance.send_message.call_args[0][0]
        assert sent_message["From"] == "noreply@example.com"
        assert sent_message["To"] == "member@example.com"
        assert sent_message["Subject"] == "Subject"
        assert sent_message.get_content().strip() == "Body"

    def test_skips_starttls_when_use_tls_is_false(self):
        """The exact case a local catcher (Mailpit, MailHog, ...) needs —
        see `SMTPEmailSender.__init__`'s docstring for why `starttls()`
        would otherwise raise `SMTPNotSupportedError` against one."""
        smtp_cls, smtp_instance = self._make_smtp_mock()
        sender = SMTPEmailSender(
            host="localhost",
            port=1025,
            username=None,
            password=None,
            from_address="noreply@library.local",
            use_tls=False,
        )

        with patch("app.core.notifications.smtplib.SMTP", smtp_cls):
            asyncio.run(sender.send("member@example.com", "Subject", "Body"))

        smtp_instance.starttls.assert_not_called()
        smtp_instance.login.assert_not_called()
        smtp_instance.send_message.assert_called_once()

    def test_skips_login_when_credentials_are_not_configured(self):
        smtp_cls, smtp_instance = self._make_smtp_mock()
        sender = SMTPEmailSender(
            host="smtp.example.com",
            port=587,
            username=None,
            password=None,
            from_address="noreply@example.com",
            use_tls=True,
        )

        with patch("app.core.notifications.smtplib.SMTP", smtp_cls):
            asyncio.run(sender.send("member@example.com", "Subject", "Body"))

        smtp_instance.starttls.assert_called_once()
        smtp_instance.login.assert_not_called()


class _FailingNotifier(Notifier):
    """Test double: always raises, to prove `CompositeNotifier` isolates
    one bad channel from the others."""

    async def notify(self, notification: Notification) -> None:
        raise RuntimeError("channel is down")


class TestCompositeNotifier:
    def test_fans_out_to_every_channel(self):
        websocket_sink = InMemoryNotifier()
        email_sender = InMemoryEmailSender()
        composite = CompositeNotifier([websocket_sink, EmailNotifier(email_sender)])
        notification = _make_notification(email="member@example.com")

        asyncio.run(composite.notify(notification))

        assert websocket_sink.sent_to(notification.user_id) == [notification]
        assert len(email_sender.sent_to("member@example.com")) == 1

    def test_one_failing_channel_does_not_block_the_others(self):
        websocket_sink = InMemoryNotifier()
        composite = CompositeNotifier([_FailingNotifier(), websocket_sink])
        notification = _make_notification()

        # Must not raise — a dead channel is logged, not propagated.
        asyncio.run(composite.notify(notification))

        assert websocket_sink.sent_to(notification.user_id) == [notification]
