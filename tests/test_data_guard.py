import pytest

from app.guards.output.data_guard import DataGuard, OutputAction


def test_clean_output_passes_unchanged():
    guard = DataGuard()
    text = "Python decorator is a callable wrapper."

    result = guard.analyze(text)

    assert result.action == OutputAction.PASS
    assert result.findings == ()
    assert result.redaction_count == 0
    assert result.text == text


def test_email_is_redacted():
    result = DataGuard().analyze("Contact me at user@example.com")

    assert result.action == OutputAction.REDACT
    assert result.findings == ("email",)
    assert result.redaction_count == 1
    assert "user@example.com" not in result.text
    assert "[REDACTED_EMAIL]" in result.text


def test_phone_and_api_key_are_redacted():
    result = DataGuard().analyze(
        "Phone: 05551234567 Key: sk-abcdefghijklmnopqrstuvwxyz123456"
    )

    assert "turkish_mobile_phone" in result.findings
    assert "api_key" in result.findings
    assert result.redaction_count == 2
    assert "05551234567" not in result.text
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result.text


def test_valid_turkish_iban_is_redacted():
    value = "TR20 0000 0000 0000 0000 0000 01"

    result = DataGuard().analyze(f"IBAN: {value}")

    assert result.findings == ("turkish_iban",)
    assert "[REDACTED_IBAN]" in result.text
    assert value not in result.text


def test_invalid_turkish_iban_is_not_redacted():
    value = "TR21 0000 0000 0000 0000 0000 01"

    result = DataGuard().analyze(f"Reference: {value}")

    assert result.action == OutputAction.PASS
    assert result.redaction_count == 0
    assert value in result.text


def test_luhn_valid_card_is_redacted():
    value = "4242 4242 4242 4242"

    result = DataGuard().analyze(f"Card: {value}")

    assert result.findings == ("payment_card",)
    assert "[REDACTED_CARD]" in result.text
    assert value not in result.text


def test_invalid_long_number_is_not_treated_as_card():
    value = "1234 5678 9012 3456"

    result = DataGuard().analyze(f"Order reference: {value}")

    assert result.action == OutputAction.PASS
    assert value in result.text


@pytest.mark.parametrize(
    ("value", "finding", "replacement"),
    [
        (
            "gsk_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "api_key",
            "[REDACTED_API_KEY]",
        ),
        (
            "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN",
            "github_token",
            "[REDACTED_GITHUB_TOKEN]",
        ),
        (
            "AKIAABCDEFGHIJKLMNOP",
            "aws_access_key_id",
            "[REDACTED_AWS_ACCESS_KEY_ID]",
        ),
        (
            "xoxb-1234567890-abcdefghij",
            "slack_token",
            "[REDACTED_SLACK_TOKEN]",
        ),
    ],
)
def test_provider_tokens_are_redacted(value, finding, replacement):
    result = DataGuard().analyze(f"credential={value}")

    assert finding in result.findings
    assert value not in result.text
    assert replacement in result.text


def test_private_key_block_is_redacted_as_one_finding():
    value = (
        "-----BEGIN PRIVATE KEY-----\n"
        "not-a-real-key-material\n"
        "-----END PRIVATE KEY-----"
    )

    result = DataGuard().analyze(
        f"Do not expose this:\n{value}\nDone."
    )

    assert result.findings == ("private_key",)
    assert result.redaction_count == 1
    assert value not in result.text
    assert "[REDACTED_PRIVATE_KEY]" in result.text


def test_multiple_sensitive_values_are_all_redacted():
    text = (
        "Email user@example.com, "
        "IBAN TR20 0000 0000 0000 0000 0000 01, "
        "card 4242-4242-4242-4242."
    )

    result = DataGuard().analyze(text)

    assert set(result.findings) == {
        "email",
        "turkish_iban",
        "payment_card",
    }
    assert result.redaction_count == 3
    assert "user@example.com" not in result.text
    assert "TR20" not in result.text
    assert "4242-4242-4242-4242" not in result.text


def test_non_string_input_is_rejected():
    with pytest.raises(TypeError):
        DataGuard().analyze(None)
