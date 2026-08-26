import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleDefinition:
    """A static detection rule used by RuleGuard."""

    rule_id: str
    weight: float
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class RuleMatch:
    """Evidence produced when one detection rule matches."""

    rule_id: str
    weight: float
    matched_text: str


@dataclass(frozen=True)
class RuleGuardResult:
    """RuleGuard analysis output.

    This is evidence plus a heuristic score, not an ALLOW/BLOCK decision.
    """

    score: float
    matches: tuple[RuleMatch, ...]

    @property
    def matched_rules(self) -> tuple[str, ...]:
        return tuple(match.rule_id for match in self.matches)


RULES = (
    RuleDefinition(
        rule_id="instruction_override",
        weight=0.55,
        patterns=(
            r"\bignore\s+(all\s+)?(previous|prior)\s+instructions?\b",
            r"\bforget\s+(all\s+)?(previous|prior)\s+instructions?\b",
            r"\bdisregard\s+(all\s+)?(previous|prior)\s+instructions?\b",
            r"\boverride\s+(the\s+)?(previous|prior)\s+instructions?\b",
            r"\b(önceki|önce)\s+(tüm\s+)?talimatları\s+"
            r"(yok\s+say|unut|görmezden\s+gel)\b",
        ),
    ),
    RuleDefinition(
        rule_id="system_prompt_exfiltration",
        weight=0.65,
        patterns=(
            r"\b(reveal|show|print|display|output)\s+"
            r"(me\s+)?(your\s+)?"
            r"(system|developer|hidden)\s+"
            r"(prompt|instructions?)\b",
            r"\bwhat\s+(is|are)\s+(your\s+)?"
            r"(system|developer|hidden)\s+"
            r"(prompt|instructions?)\b",
            r"\b(sistem|geliştirici)\s+"
            r"(promptunu|talimatlarını)\s+"
            r"(göster|açıkla|yazdır|ver)\b",
        ),
    ),
    RuleDefinition(
        rule_id="security_bypass",
        weight=0.60,
        patterns=(
            r"\b(bypass|disable|ignore|remove)\s+"
            r"(your\s+)?(safety|security)\s+"
            r"(rules?|filters?|restrictions?|guardrails?)\b",
            r"\bdisable\s+(all\s+)?"
            r"(filters?|restrictions?|guardrails?)\b",
            r"\b(güvenlik|emniyet)\s+"
            r"(kurallarını|filtrelerini|kısıtlamalarını)\s+"
            r"(devre\s+dışı\s+bırak|atla|yok\s+say)\b",
        ),
    ),
    RuleDefinition(
        rule_id="jailbreak_mode",
        weight=0.50,
        patterns=(
            r"\b(jailbreak|dan\s+mode|developer\s+mode)\b",
            r"\b(dan\s+modu|geliştirici\s+modu)\b",
        ),
    ),
)


class RuleGuard:
    """Fast, deterministic baseline detector for obvious prompt-injection patterns."""

    @staticmethod
    def normalize(text: str) -> str:
        """Canonicalize user text before regex matching."""

        normalized = unicodedata.normalize("NFKC", text)

        for character in ("\u200b", "\u200c", "\u200d", "\ufeff"):
            normalized = normalized.replace(character, "")

        normalized = normalized.lower()
        return " ".join(normalized.split())

    def analyze(self, text: str) -> RuleGuardResult:
        """Return matched rule evidence and a bounded heuristic risk score."""

        if not isinstance(text, str):
            raise TypeError("RuleGuard input must be a string")

        normalized_text = self.normalize(text)
        matches: list[RuleMatch] = []

        for rule in RULES:
            for pattern in rule.patterns:
                match = re.search(pattern, normalized_text)

                if match:
                    matches.append(
                        RuleMatch(
                            rule_id=rule.rule_id,
                            weight=rule.weight,
                            matched_text=match.group(0),
                        )
                    )
                    # A rule contributes at most once, even if multiple variants match.
                    break

        score = min(sum(match.weight for match in matches), 1.0)

        return RuleGuardResult(
            score=round(score, 2),
            matches=tuple(matches),
        )
