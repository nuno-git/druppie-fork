"""Tests for Notificatie Module v1."""

import pytest

from v1.module import NotificatieModule


@pytest.fixture
def module():
    """Create a NotificatieModule instance with test defaults."""
    return NotificatieModule(
        base_url="http://mock-notificatie:8080",
        from_address="test@example.com",
    )


class TestNotificatieModuleInit:
    """Test module initialization."""

    def test_init_with_defaults(self):
        mod = NotificatieModule()
        assert mod._base_url
        assert mod._from_address

    def test_init_with_custom_params(self):
        mod = NotificatieModule(
            base_url="https://custom.example.com",
            from_address="custom@example.com",
        )
        assert mod._base_url == "https://custom.example.com"
        assert mod._from_address == "custom@example.com"

    def test_init_strips_trailing_slash(self):
        mod = NotificatieModule(base_url="https://example.com/")
        assert mod._base_url == "https://example.com"


class TestSendEmail:
    """Test send_email method."""

    @pytest.mark.asyncio
    async def test_send_email_validates_recipients(self, module):
        """Empty recipients list should raise ValueError."""
        with pytest.raises(ValueError, match="recipient"):
            await module.send_email(
                ontvangers=[],
                onderwerp="Test",
                body="Test body",
            )

    @pytest.mark.asyncio
    async def test_send_email_validates_subject(self, module):
        """Empty subject should raise ValueError."""
        with pytest.raises(ValueError, match="onderwerp|Subject"):
            await module.send_email(
                ontvangers=["test@example.com"],
                onderwerp="",
                body="Test body",
            )

    @pytest.mark.asyncio
    async def test_send_email_validates_body(self, module):
        """Empty body should raise ValueError."""
        with pytest.raises(ValueError, match="Body"):
            await module.send_email(
                ontvangers=["test@example.com"],
                onderwerp="Test",
                body="",
            )

    def test_method_signature(self, module):
        """Verify send_email accepts expected params."""
        import inspect

        sig = inspect.signature(module.send_email)
        params = list(sig.parameters.keys())
        assert "ontvangers" in params
        assert "onderwerp" in params
        assert "body" in params
        assert "sjabloon" in params
        assert "bijlagen" in params


class TestSendPush:
    """Test send_push method."""

    @pytest.mark.asyncio
    async def test_send_push_returns_stub(self, module):
        """send_push returns stub response."""
        result = await module.send_push(
            kanaal="team-geluid",
            bericht="Nieuwe melding",
        )
        assert result["status"] == "stub"
        assert result["kanaal"] == "team-geluid"
        assert result["bericht"] == "Nieuwe melding"

    def test_method_signature(self, module):
        """Verify send_push accepts expected params."""
        import inspect

        sig = inspect.signature(module.send_push)
        params = list(sig.parameters.keys())
        assert "kanaal" in params
        assert "bericht" in params
