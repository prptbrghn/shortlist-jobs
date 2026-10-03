"""Treat text from job pages as untrusted data.

``sanitize_text`` strips HTML (including scripts, styles and comments), removes zero-width and
control characters, collapses whitespace, caps the length and flags instruction-like phrases
(prompt-injection attempts). It returns ``(clean_text, warnings)``. Flagging is a heuristic:
it reduces risk but cannot guarantee that every injection attempt is caught, so downstream
agents must still treat all page content as data, never as instructions.

``is_safe_url`` accepts only http(s) URLs with a hostname and no embedded credentials.
"""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import urlsplit

DEFAULT_MAX_LENGTH = 4000
REDACTION = "[removed: instruction-like text]"

_ZERO_WIDTH_RE = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u202a-\u202e\u2066-\u2069]"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLOCK_RE = re.compile(r"<(script|style|iframe|object|embed|noscript)\b.*?(?:</\1\s*>|$)", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?(?:-->|$)", re.S)
_TAG_RE = re.compile(r"</?[a-zA-Z][^<>]*>")
_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?;|])\s+|\n+")

_GAP = r"[\w\s,'/-]{0,40}?"  # a short run of ordinary words between key terms
_AI = r"(ai|llm|assistant|agent|claude|chatgpt|gpt|model|bot|language model)"
_WHO = r"(the )?(user|candidate|human|applicant|job ?seeker)'?s?"

# (label, pattern). Patterns run on NFKC-normalised, lower-cased text with collapsed whitespace.
_PATTERN_SOURCES: list[tuple[str, str]] = [
    ("ignore previous instructions",
     r"\b(ignore|disregard|forget|skip|bypass)\b" + _GAP
     + r"\b(previous|prior|above|earlier|preceding|all|any|your|system|original)\b[\w\s,'-]{0,20}?"
     r"\b(instructions?|prompts?|rules|directions|guidelines|messages?|context)\b"),
    ("override rules",
     r"\b(override|overrule|bypass|disable|turn off)\b[\w\s,'-]{0,20}?\b(your|the|all|any|previous|safety|content)\b"
     r"[\w\s,'-]{0,15}?\b(instructions?|rules|safety|guardrails|system prompt|restrictions|filters)\b"),
    ("role reassignment",
     r"\byou are now (a|an|the|in|my)\b|\bfrom now on,? you (are|will|must|should)\b|\bpretend (to be|you are)\b|"
     r"\broleplay as\b|\bact as (an? |the )?(unrestricted|different|new|evil|jailbroken)?\s?" + _AI + r"\b|"
     r"\byour (new|real|true) (role|task|job|instructions?|purpose) (is|are)\b"),
    ("fake system message",
     r"\b(system|developer|admin|assistant) (prompt|message|note|override|instruction)s?\b|^(system|assistant)\s*:|"
     r"<\|?(im_start|im_end|system|endoftext)\|?>|\[/?inst\]|<</?sys>>|###\s*(system|instruction)"),
    ("new instructions",
     r"\b(new|updated|additional|hidden|secret|real|important) (instructions?|directives?|orders?)\s*[:\-]"),
    ("addressed to the AI",
     r"\b(note|message|attention|instructions?|reminder) (to|for) (the |any |all )?" + _AI + r"s?\b|"
     r"\bif you are an? " + _AI + r"\b|\b(dear|hey|hi|hello) " + _AI + r"\b|\b" + _AI
     + r"s? (reading|processing|parsing|summari[sz]ing) this\b"),
    ("data exfiltration",
     r"\b(send|email|e-mail|forward|share|upload|post|leak|paste|transmit|exfiltrate)\b" + _GAP
     + r"\b(" + _WHO + r"|their|all|any|every)\b[\w\s,'-]{0,20}?\b(resume|cv|fact sheet|profile|personal|data|details|"
     r"information|files?|conversation|chat history|memory|tracker|contacts?)\b|"
     r"\b(send|email|e-mail|forward|upload|post|leak|transmit|exfiltrate)\b" + _GAP
     + r"\bto\s+(\S+@\S+\.\w+|https?://\S+)"),
    ("credential request",
     r"\b(enter|provide|share|send|give|type|paste|reveal|include|submit|tell me|disclose)\b" + _GAP
     + r"\b(password|passcode|api[ _-]?key|access token|secret key|credentials|one[- ]time (password|code)|otp|"
     r"2fa code|ssh key|bank account|credit card|card number|cvv|social security|ssn|passport number)s?\b"),
    ("auto-apply / submit",
     r"\b(submit|send|complete|fill (in|out)|auto-?apply)\b[\w\s,'-]{0,60}?"
     r"\b(on (their|my|his|her|" + _WHO + r") behalf|automatically|without (review|asking|"
     r"confirmation|approval|telling|checking)|for (the|this) (user|candidate))\b"),
    ("login request",
     r"\b(log ?in|sign ?in|authenticate)\b[\w\s,'-]{0,30}?\b(as (the )?(user|candidate)|with (the |their |your )?"
     r"(" + _WHO + r" )?(credentials|password|account details))\b"),
    ("command execution",
     r"\b(run|execute|eval)\b (this|the following|these|below) (command|code|script|shell)s?\b|"
     r"\bcurl\s+(-\S+\s+)*https?://|\bwget\s+https?://|\brm\s+-rf\b|\binvoke-webrequest\b|"
     r"\bpowershell\s+-e(nc|ncodedcommand)?\b|\biex\s*\("),
    ("score manipulation",
     r"\b(rate|score|rank|mark|give|assign)\b[\w\s,'-]{0,30}?\b(10\s*/\s*10|10 out of 10|perfect (score|match|fit)|"
     r"highest (score|priority|rating|rank)|100 ?%? (score|match))|"
     r"\b(match score|priority( score)?)\b[\w\s,'-]{0,15}?\b(to|of|=|should be|must be)\s*(10|100)\b"),
    ("secrecy request",
     r"\b(do not|don't|never) (tell|inform|mention|reveal|show|alert)\b[\w\s,'-]{0,20}?\b(user|candidate|human|"
     r"anyone|applicant)\b|\bwithout (telling|informing|notifying|alerting) (the )?(user|candidate|human|anyone)\b|"
     r"\bkeep this (secret|hidden|between us|confidential from)\b"),
    ("jailbreak keyword",
     r"\b(jailbreak|jailbroken|dan mode|developer mode|do anything now|prompt injection)\b"),
]
INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(src, re.I | re.M)) for label, src in _PATTERN_SOURCES
]


def strip_html(text: str) -> tuple[str, list[str]]:
    """Remove script/style blocks, comments and tags; unescape entities."""
    warnings: list[str] = []
    out = text
    if _BLOCK_RE.search(out):
        warnings.append("removed script/style/embedded content")
        out = _BLOCK_RE.sub(" ", out)
    if _COMMENT_RE.search(out):
        warnings.append("removed HTML comments")
        out = _COMMENT_RE.sub(" ", out)
    out = _TAG_RE.sub(" ", out)
    out = html.unescape(out)
    # A second pass catches tags that were entity-encoded (e.g. &lt;script&gt;).
    if _BLOCK_RE.search(out) or _TAG_RE.search(out):
        warnings.append("removed encoded HTML")
        out = _TAG_RE.sub(" ", _BLOCK_RE.sub(" ", out))
    return out, warnings


def _normalise_for_matching(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH_RE.sub("", t)
    return _WS_RE.sub(" ", t).strip().lower()


def find_injections(text: str) -> list[str]:
    """Return labels of instruction-like patterns found in ``text`` (empty if none)."""
    t = _normalise_for_matching(text)
    return [label for label, pattern in INJECTION_PATTERNS if pattern.search(t)]


def redact_injections(text: str) -> str:
    """Replace every sentence that contains instruction-like text with a placeholder."""
    parts = _SENTENCE_RE.split(text)
    out = " ".join(REDACTION if find_injections(p) else p for p in parts)
    out = re.sub(rf"(?:{re.escape(REDACTION)}\s*)+", REDACTION + " ", out).strip()
    # A pattern spanning two sentences survives the split; remove what is left of it.
    for _, pattern in INJECTION_PATTERNS:
        out = pattern.sub(REDACTION, out)
    return _WS_RE.sub(" ", out).strip()


def sanitize_text(
    text: object,
    max_length: int = DEFAULT_MAX_LENGTH,
    redact: bool = False,
) -> tuple[str, list[str]]:
    """Clean untrusted text and report anything suspicious.

    Steps: coerce to str, NFKC-normalise, strip HTML, drop zero-width/bidi/control characters,
    collapse whitespace, flag instruction-like phrases (optionally redacting them), cap length.
    Returns ``(clean_text, warnings)``. A warning starting with ``instruction-like text`` means a
    possible prompt injection.
    """
    if text is None:
        return "", []
    warnings: list[str] = []
    out = unicodedata.normalize("NFKC", str(text))
    out, html_warnings = strip_html(out)
    warnings.extend(html_warnings)
    if _ZERO_WIDTH_RE.search(out):
        warnings.append("removed zero-width or direction-control characters")
        out = _ZERO_WIDTH_RE.sub("", out)
    if _CONTROL_RE.search(out):
        warnings.append("removed control characters")
        out = _CONTROL_RE.sub(" ", out)
    out = _WS_RE.sub(" ", out).strip()

    labels = find_injections(out)
    # Instructions hidden in removed HTML (comments, scripts, tags) are still worth reporting.
    hidden = [lb for lb in find_injections(html.unescape(unicodedata.normalize("NFKC", str(text))))
              if lb not in labels]
    if labels:
        warnings.append("instruction-like text: " + ", ".join(labels))
        if redact:
            out = redact_injections(out)
    if hidden:
        warnings.append("instruction-like text in hidden HTML (removed): " + ", ".join(hidden))

    if max_length and len(out) > max_length:
        warnings.append(f"truncated to {max_length} characters")
        out = out[:max_length].rstrip() + "..."
    return out, warnings


def is_injection_warning(warnings: list[str]) -> bool:
    """True if any warning reports instruction-like text."""
    return any(w.startswith("instruction-like text") for w in warnings)


def is_safe_url(url: object) -> bool:
    """True for http(s) URLs with a hostname, no embedded credentials and no whitespace/control chars."""
    return validate_url(url)[0]


def validate_url(url: object) -> tuple[bool, str]:
    """Check a job link. Returns ``(ok, reason)``; reason is ``"ok"`` when accepted."""
    if not isinstance(url, str) or not url.strip():
        return False, "missing URL"
    if url != url.strip() or any(ch.isspace() for ch in url) or _CONTROL_RE.search(url) or _ZERO_WIDTH_RE.search(url):
        return False, "URL contains whitespace or hidden characters"
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError for a malformed port
    except ValueError:
        return False, "malformed URL"
    if parts.scheme.lower() not in ("http", "https"):
        return False, f"unsupported scheme {parts.scheme!r}" if parts.scheme else "not an absolute http(s) URL"
    if not host:
        return False, "URL has no hostname"
    if parts.username is not None or parts.password is not None:
        return False, "URL contains embedded credentials"
    if not ("." in host or host == "localhost" or ":" in host):
        return False, "hostname is not a domain"
    return True, "ok"
