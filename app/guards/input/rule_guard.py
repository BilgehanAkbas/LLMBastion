import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    weight: float
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    weight: float
    matched_text: str


@dataclass(frozen=True)
class RuleGuardResult:
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

META_CONTEXT_PATTERNS = (
    r"\b(explain|define|describe)\s+(why\s+)?(the\s+)?(term|phrase|sentence|concept)\b",
    r"\bin\s+the\s+context\s+of\b",
    r"\bassociated\s+with\s+prompt\s+injection\b",
    r"\b(terimi|ifadesi|ifadesini|cümlesi|cümlesini)\b.*\b(ne|neyi)\s+ifade\s+ediyor\b",
)

META_CONTEXT_MULTIPLIER = 0.40


class RuleGuard:
    """Fast, deterministic baseline detector for obvious prompt injection."""

    @staticmethod
    def normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text)

        for character in ("\u200b", "\u200c", "\u200d", "\ufeff"):
            normalized = normalized.replace(character, "")

        normalized = normalized.lower()
        return " ".join(normalized.split())

    @staticmethod
    def _is_quoted(normalized_text: str, matched_text: str) -> bool:
        quote_pairs = (
            ("'", "'"),
            ('"', '"'),
            ("“", "”"),
            ("‘", "’"),
        )

        for occurrence in re.finditer(
            re.escape(matched_text),
            normalized_text,
        ):
            start = occurrence.start()
            end = occurrence.end()

            for opening, closing in quote_pairs:
                left = normalized_text.rfind(opening, 0, start + 1)
                right = normalized_text.find(closing, end)

                if left != -1 and right != -1 and left < start < right:
                    return True

        return False

    @staticmethod
    def _has_meta_context(normalized_text: str) -> bool:
        return any(
            re.search(pattern, normalized_text)
            for pattern in META_CONTEXT_PATTERNS
        )

    def analyze(self, text: str) -> RuleGuardResult:
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
                    break

        # Context reduction is match-local. A harmless quoted example no longer
        # reduces the confidence of a separate direct attack in the same prompt.
        meta_context = self._has_meta_context(normalized_text)
        effective_weights: list[float] = []

        for match in matches:
            weight = match.weight
            if self._is_quoted(normalized_text, match.matched_text):
                weight *= META_CONTEXT_MULTIPLIER
            elif meta_context and len(matches) == 1:
                weight *= META_CONTEXT_MULTIPLIER
            effective_weights.append(weight)

        score = min(sum(effective_weights), 1.0)

        return RuleGuardResult(
            score=round(score, 2),
            matches=tuple(matches),
        )
