from app.guards.output.data_guard import DataGuard, OutputAction


def test_clean_output_passes_unchanged():
    guard = DataGuard()

    result = guard.analyze("Python decorator is a callable wrapper.")

    assert result.action == OutputAction.PASS
    assert result.findings == ()
    assert result.text == "Python decorator is a callable wrapper."


def test_email_is_redacted():
    guard = DataGuard()

    result = guard.analyze("Contact me at user@example.com")

    assert result.action == OutputAction.REDACT
    assert result.findings == ("email",)
    assert "user@example.com" not in result.text
    assert "[REDACTED_EMAIL]" in result.text


def test_phone_and_api_key_are_redacted():
    guard = DataGuard()

    result = guard.analyze(
        "Phone: 05551234567 Key: sk-abcdefghijklmnopqrstuvwxyz123456"
    )

    assert result.action == OutputAction.REDACT
    assert "turkish_mobile_phone" in result.findings
    assert "api_key" in result.findings
    assert "05551234567" not in result.text
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result.text
