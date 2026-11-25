"""
Shared preprocessing pipeline for the Anime/Game forum corpus.

Use this same module for:
- preprocessing corpus documents (member 2)
- preprocessing search queries (member 3)
- preprocessing evaluation queries (member 4)

Pipeline: HTML/URL/email cleaning -> tokenization -> stopword removal
-> English Snowball stemming.

Important: do not create a separate query-only version of these functions.
"""

import html
import re
import unicodedata
from typing import Any

import nltk
from nltk.corpus import stopwords
from nltk.stem import SnowballStemmer


# Fixed English stopword list based on the standard NLTK English vocabulary.
# Keeping it in this module makes preprocessing reproducible and avoids a
# separate NLTK corpus download on every team member's machine.
ENGLISH_STOPWORDS = set("""
i me my myself we our ours ourselves you you're you've you'll you'd your yours
yourself yourselves he him his himself she she's her hers herself it it's its
itself they them their theirs themselves what which who whom this that that'll
these those am is are was were be been being have has had having do does did
doing a an the and but if or because as until while of at by for with about
against between into through during before after above below to from up down
in out on off over under again further then once here there when where why how
all any both each few more most other some such no nor not only own same so
than too very s t can will just don don't should should've now d ll m o re ve y
ain aren aren't couldn couldn't didn didn't doesn doesn't hadn hadn't hasn
hasn't haven haven't isn isn't ma mightn mightn't mustn mustn't needn needn't
shan shan't shouldn't was wasn't weren weren't won wouldn't
""".split())

# Elemen antarmuka/forum yang tidak membantu pencarian topik.
# Istilah penting domain anime/game sengaja tidak dimasukkan.
CUSTOM_STOPWORDS = {
    "offline", "online", "avatar", "joined", "messages", "likes", "reply",
    "replies", "quote", "quoted", "click", "profile", "report", "edit",
    "page", "thread",
}
STOPWORDS = ENGLISH_STOPWORDS | CUSTOM_STOPWORDS

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)

EN_STEMMER = SnowballStemmer("english")


def clean_text(text: Any) -> str:
    """Decode HTML, remove markup/URLs/emails, normalize and lowercase text."""
    if text is None:
        return ""
    text = html.unescape(str(text))
    text = unicodedata.normalize("NFKC", text)
    text = URL_RE.sub(" ", text)
    text = EMAIL_RE.sub(" ", text)
    text = re.sub(r"<[^>]*>", " ", text)
    text = text.casefold()
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: Any) -> list[str]:
    """Convert cleaned text into tokens."""
    return TOKEN_RE.findall(clean_text(text))


def remove_stopwords(
    tokens: list[str],
    extra_stopwords: set[str] | None = None,
) -> list[str]:
    """Remove library and optional additional stopwords."""
    stopwords_all = STOPWORDS | {
        word.casefold() for word in (extra_stopwords or set())
    }
    return [
        token for token in tokens
        if token not in stopwords_all and len(token) > 1
    ]


def stem_tokens(tokens: list[str]) -> list[str]:
    """Apply English Snowball stemming to tokens."""
    return [EN_STEMMER.stem(token) for token in tokens]


def preprocess_text(
    text: Any,
    extra_stopwords: set[str] | None = None,
) -> str:
    """
    Full preprocessing pipeline.

    """
    tokens = tokenize(text)
    tokens = remove_stopwords(tokens, extra_stopwords)
    return " ".join(stem_tokens(tokens))


def preprocess_document(document: dict[str, Any]) -> dict[str, Any]:
    """Preserve original metadata and append processed title/content/text."""
    result = dict(document)
    result["title_processed"] = preprocess_text(document.get("title", ""))
    result["content_processed"] = preprocess_text(document.get("content", ""))
    result["text_processed"] = " ".join(
        part for part in (
            result["title_processed"],
            result["content_processed"],
        ) if part
    )
    return result
