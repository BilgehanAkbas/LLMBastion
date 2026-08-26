import re
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


PATTERNS = (
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
        pattern=r"\b(?:AIza[0-9A-Za-z_-]{25,}|sk-[0-9A-Za-z_-]{20,})\b",
        replacement="[REDACTED_API_KEY]",
    ),
    SensitivePattern(
        finding_type="jwt",
        pattern=r"\beyJ[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\b",
        replacement="[REDACTED_JWT]",
    ),
)


class DataGuard:
    """Synchronous output guard that redacts obvious sensitive values."""

    def analyze(self, text: str) -> DataGuardResult:
        if not isinstance(text, str):
            raise TypeError("DataGuard input must be a string")

        redacted_text = text
        findings: list[str] = []

        for definition in PATTERNS:
            if re.search(definition.pattern, redacted_text):
                redacted_text = re.sub(
                    definition.pattern,
                    definition.replacement,
                    redacted_text,
                )
                findings.append(definition.finding_type)

        action = OutputAction.REDACT if findings else OutputAction.PASS

        return DataGuardResult(
            action=action,
            text=redacted_text,
            findings=tuple(findings),
        )
