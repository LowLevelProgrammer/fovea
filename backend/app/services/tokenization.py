import re
from collections.abc import Collection


DEFAULT_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "episode", "for", "from", "how", "in", "into", "is", "it", "learn", "of", "on", "or",
    "over", "part", "that", "the", "these", "this", "those", "to", "tutorial",
    "under", "using", "video", "was", "watch", "were", "what", "when", "where",
    "which", "why", "with",
})


def tokenize(text: str, stop_words: Collection[str] = DEFAULT_STOP_WORDS) -> set[str]:
    """Return normalized, meaningful title or query terms.

    Callers can pass a project-specific stop-word collection without changing
    recommendation logic.
    """
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in stop_words
    }
