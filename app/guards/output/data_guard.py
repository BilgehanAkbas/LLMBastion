import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class OutputAction(str, Enum):
    PASS = "PASS"
    REDACT = "REDACT"


@dataclass(frozen=True)
class SensitivePattern:
    finding_type: str
    pattern: str
    replacement: str


@dataclass(frozen=True)
class DataGuardResult:
    action: OutputAction
    text: str
    findings: tuple[str, ...]
    redaction_count: int


STATIC_PATTERNS = (
    SensitivePattern(
        finding_type="private_key",
        pattern=(
            r"-----BEGIN (?P<kind>(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY)-----"
            r"[\s\S]*?"
            r"-----END (?P=kind)-----"
        ),
        replacement="[REDACTED_PRIVATE_KEY]",
    ),
    SensitivePattern(
        finding_type="email",
        pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        replacement="[REDACTED_EMAIL]",
    ),
    SensitivePattern(
        finding_type="turkish_mobile_phone",
        pattern=r"(?<!\d)(?:\+90|0)?5\d{9}(?!\d)",
        replacement="[REDACTED_PHONE]",
    ),
    SensitivePattern(
        finding_type="api_key",
        pattern=(
            r"\b(?:"
            r"AIza[0-9A-Za-z_-]{25,}"
            r"|sk-[0-9A-Za-z_-]{20,}"
            r"|gsk_[0-9A-Za-z]{20,}"
            r")\b"
        ),
        replacement="[REDACTED_API_KEY]",
    ),
    SensitivePattern(
        finding_type="github_token",
        pattern=r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
        replacement="[REDACTED_GITHUB_TOKEN]",
    ),
    SensitivePattern(
        finding_type="aws_access_key_id",
        pattern=r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        replacement="[REDACTED_AWS_ACCESS_KEY_ID]",
    ),
    SensitivePattern(
        finding_type="slack_token",
        pattern=r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b",
        replacement="[REDACTED_SLACK_TOKEN]",
    ),
    SensitivePattern(
        finding_type="jwt",
        pattern=r"\beyJ[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\b",
        replacement="[REDACTED_JWT]",
    ),
)

TURKISH_IBAN_PATTERN = re.compile(
    r"\bTR\d{2}(?:[ -]?\d){22}\b",
    re.IGNORECASE,
)
CARD_CANDIDATE_PATTERN = re.compile(
    r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"
)


def _normalize_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _is_valid_turkish_iban(value: str) -> bool:
    normalized = re.sub(r"[\s-]+", "", value).upper()
    if not re.fullmatch(r"TR\d{24}", normalized):
        return False

    rearranged = normalized[4:] + normalized[:4]
    numeric = "".join(
        str(ord(char) - 55) if char.isalpha() else char
        for char in rearranged
    )

    remainder = 0
    for digit in numeric:
        remainder = (remainder * 10 + int(digit)) % 97

    return remainder == 1


def _passes_luhn(value: str) -> bool:
    digits = _normalize_digits(value)
    if not 13 <= len(digits) <= 19:
        return False

    # Avoid treating repeated dummy/reference numbers such as 0000... as cards.
    if len(set(digits)) == 1:
        return False

    total = 0
    parity = len(digits) % 2

    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit

    return total % 10 == 0


def _redact_validated(
    text: str,
    pattern: re.Pattern[str],
    validator: Callable[[str], bool],
    replacement: str,
) -> tuple[str, int]:
    redaction_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal redaction_count

        value = match.group(0)
        if not validator(value):
            return value

        redaction_count += 1
        return replacement

    return pattern.sub(replace, text), redaction_count


class DataGuard:
    """Synchronous output guard for deterministic sensitive-data redaction."""

    def analyze(self, text: str) -> DataGuardResult:
        if not isinstance(text, str):
            raise TypeError("DataGuard input must be a string")

        redacted_text = text
        findings: list[str] = []
        redaction_count = 0

        # First redact structures with strong, explicit signatures.
        for definition in STATIC_PATTERNS:
            redacted_text, count = re.subn(
                definition.pattern,
                definition.replacement,
                redacted_text,
            )
            if count:
                findings.append(definition.finding_type)
                redaction_count += count

        # Turkish IBAN: regex creates a candidate; MOD-97 confirms it.
        redacted_text, iban_count = _redact_validated(
            redacted_text,
            TURKISH_IBAN_PATTERN,
            _is_valid_turkish_iban,
            "[REDACTED_IBAN]",
        )
        if iban_count:
            findings.append("turkish_iban")
            redaction_count += iban_count

        # Payment card: regex creates a candidate; Luhn reduces false positives.
        redacted_text, card_count = _redact_validated(
            redacted_text,
            CARD_CANDIDATE_PATTERN,
            _passes_luhn,
            "[REDACTED_CARD]",
        )
        if card_count:
            findings.append("payment_card")
            redaction_count += card_count

        action = (
            OutputAction.REDACT
            if redaction_count
            else OutputAction.PASS
        )

        return DataGuardResult(
            action=action,
            text=redacted_text,
            findings=tuple(findings),
            redaction_count=redaction_count,
        )
