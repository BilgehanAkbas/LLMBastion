"""Conservative adapter for local text work; never makes a policy decision."""
from dataclasses import dataclass
import re
import unicodedata

from .rule_guard import RuleGuard, RuleGuardResult


# These vetoes supplement RuleGuard's attack rules: merely naming a protected
# target is enough to refuse an exception, even without an explicit attack verb.
_PROTECTED = re.compile(
    r"\b(?:system\w*|sistem\w*|developer\w*|gelistirici\w*|hidden|gizli\w*|"
    r"secret\w*|internal|dahili\w*|instruction\w*|direction\w*|talimat\w*|yonerge\w*|"
    r"prompt\w*|policy|policies|politika\w*|guard\w*|safety|security|guvenlik\w*|"
    r"admin\w*|yonetici\w*|credential\w*|password\w*|sifre\w*|token\w*|"
    r"private|confidential|ozel|anahtar\w*|tool\w*|arac\w*|memory|rag)\b"
)
_MANIPULATION = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass\w*|disable|reveal|exfiltrat\w*|"
    r"obey|execute|disclose|expose|show|print|display|output|jailbreak|dan|"
    r"goster\w*|yazdir\w*|unut\w*|atla\w*|calistir\w*|sizdir\w*)\b|"
    r"\b(?:yok say|gecersiz say|gorme[z]*den gel|devre disi|act as|"
    r"(?:follow|comply(?: with)?) only|follow (?:me|my)|"
    r"(?:sadece|yalniz(?:ca)?) (?:bu|benim)|no longer appl\w*|"
    r"instead of|yerine benim|you are now|from now on|henceforth|unrestricted|"
    r"uncensored|without restrictions|sen artik|artik sen|bundan sonra)\b"
)
_ENCODED_OR_STRUCTURED = re.compile(
    r"[\[\]<>`\\]|\b(?:base64|hex|rot13|unicode|encoded|decode|decoding)\b|"
    r"(?:https?://|%[0-9a-f]{2})"
)
_TEXT = r"(?:metni|cumleyi|paragrafi|mesaji|taslagi)"
_LOCAL = rf"(?:bu|su|asagidaki) {_TEXT}"
_STYLE = r"(?:samimi|resmi|akici|nazik|yumusak|sade|friendly|formal)"
_PAYLOAD = r"(?:\s*:\s*.+)?[.!?]?"
_INTENTS = (
    ("tone_style", re.compile(
        rf"{_LOCAL} (?:daha )?{_STYLE} (?:yaz|yap){_PAYLOAD}|"
        rf"make (?:this|the) (?:sentence|text|message|paragraph) "
        rf"(?:(?:more|less) )?(?:friendly|friendlier|formal|polite|gentle){_PAYLOAD}"
    )),
    ("summarize_shorten", re.compile(
        rf"{_LOCAL} (?:kisalt|ozetle){_PAYLOAD}|"
        rf"(?:summarize|shorten) (?:this|the) (?:text|paragraph|message|draft){_PAYLOAD}"
    )),
    ("edit_rewrite", re.compile(
        rf"{_LOCAL} (?:(?:daha )?{_STYLE} )?"
        rf"(?:yeniden yaz|rewrite et|yaz|duzenle|duzelt){_PAYLOAD}|"
        rf"rewrite(?: (?:this|the) (?:text|sentence|paragraph|message|draft))?"
        rf"(?: (?:politely|clearly|formally|briefly))?{_PAYLOAD}"
    )),
    ("previous_draft_edit", re.compile(
        r"onceki (?:taslagin|metindeki|paragrafin|taslagi|metni|paragrafi) (?:.+ )?"
        r"(?:cikar|kaldir|sadeles?tir|duzenle|degistir(?:me)?|ozetle|kisalt)[.!?]?|"
        r"(?:replace|edit|revise|shorten|summarize|remove) (?:the )?previous "
        r"(?:draft|text|paragraph|sentence|message)(?:'s)? .+|"
        r"previous (?:paragraph|draft|text) yerine (?:sunu|bu metni) kullan\s*:\s*.+"
    )),
    ("topic_switch", re.compile(
        r"[\w -]+ konusunu birakalim[.!] simdi .+ (?:anlat|acikla)[.!?]?|"
        r"let's change the subject from [\w -]+ to [\w -]+[.!] "
        r"(?:how|what|explain|tell me) .+"
    )),
)
_LOCAL_RESET = re.compile(r"onceki (?:metni|taslagi|paragrafi) unut[,.;] (?P<edit>.+)")
_RESET_EDIT = re.compile(rf"daha {_STYLE} yaz\s*:\s*.+")


def _fold(text: str) -> str:
    normalized = RuleGuard.normalize(text).replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", normalized)
                   if not unicodedata.combining(c))


@dataclass(frozen=True)
class SemanticIntentSignal:
    original_semantic_score: float
    intent_family: str | None = None

    @property
    def effective_score(self) -> float:
        return 0.0 if self.intent_family else self.original_semantic_score

    @property
    def evidence(self) -> dict:
        if self.intent_family is None:
            return {}
        return {
            "semantic_safe_intent_override": True,
            "intent_family": self.intent_family,
            "original_semantic_score": self.original_semantic_score,
        }


def adapt_semantic_signal(text: str, rule_result: RuleGuardResult,
                          semantic_score: float, semantic_threshold: float) -> SemanticIntentSignal:
    unchanged = SemanticIntentSignal(semantic_score)
    if semantic_score < semantic_threshold or rule_result.score != 0 or rule_result.matches:
        return unchanged
    folded = _fold(text)
    # Intent patterns are TR/EN only. Mixed-script targets/homoglyphs must fall
    # back to the original detector, not gain a text-edit exception.
    if any(c.isalpha() and not c.isascii() for c in folded):
        return unchanged
    # Reuse RuleGuard even for accent-folded spellings; quoted/meta matches veto
    # an exception too, regardless of their discounted numeric score.
    if RuleGuard().analyze(text).matches or RuleGuard().analyze(folded).matches:
        return unchanged
    if _PROTECTED.search(folded) or _ENCODED_OR_STRUCTURED.search(folded):
        return unchanged
    reset = _LOCAL_RESET.fullmatch(folded)
    command = reset['edit'] if reset else folded
    if _MANIPULATION.search(command):
        return unchanged
    if reset and _RESET_EDIT.fullmatch(command):
        return SemanticIntentSignal(semantic_score, "local_context_edit")
    for family, pattern in _INTENTS:
        if pattern.fullmatch(command):
            return SemanticIntentSignal(semantic_score, family)
    return unchanged
