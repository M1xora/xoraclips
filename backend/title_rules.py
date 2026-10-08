"""
Rules for hook titles (issue #31): short, curiosity-driven Indonesian titles
for TikTok / Shorts / Reels, three options per clip.

The limits live here, not in the analysis logic, and each can be overridden
with an environment variable (for example XORACLIPS_MAX_TITLE_WORDS=6).
The visual limits come from #21/#23: the ASS title path never shrinks, and
only a single word of 17+ letters at the Big size ran past the frame (about
60 px a letter). 50 characters wrap to at most 4 lines of ~15 letters
(~900 px), and 14-letter words stay inside the 1010 px safe width.

Gemini's titles are checked here one by one. A title that breaks a rule is
logged with the reason and dropped; if none is left, a safe fallback is used.
"""
import logging
import os
import re
import unicodedata
from typing import Callable, Iterable, List, Optional, Tuple

logger = logging.getLogger("xoraclips.titles")


def _int_setting(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning(f"Ignoring {name}={raw!r}: not a whole number; using {default}.")
        return default


MAX_TITLE_WORDS = _int_setting("XORACLIPS_MAX_TITLE_WORDS", 7, 3)
MAX_TITLE_CHARS = _int_setting("XORACLIPS_MAX_TITLE_CHARS", 50, 20)
MAX_TITLE_WORD_CHARS = _int_setting("XORACLIPS_MAX_TITLE_WORD_CHARS", 14, 8)
TITLE_OPTIONS = _int_setting("XORACLIPS_TITLE_OPTIONS", 3, 1)

# Last resort when neither the new options nor the old titles are usable.
GENERIC_FALLBACK = "Momen Penting dari Video Ini"

# Words a title cannot end on after being cut ("Buka Pabrik di").
_DANGLING = {
    "di", "ke", "dari", "dan", "yang", "untuk", "soal", "dengan", "buat", "pada",
    "atau", "dalam", "sama", "karena", "tapi", "bagi", "oleh", "para", "si", "sang",
    "the", "a", "an", "of", "and", "to", "for", "in", "on", "with",
}

_QUOTES = "\"'“”‘’«»`"
_FIRST_PERSON = re.compile(r"\b(me|my|mine|myself|saya|aku|gue|gw)\b", re.IGNORECASE)


def _editor_voice(title: str) -> str:
    """The part that speaks as the editor: after "Name:" it is a quote."""
    head, sep, _quote = title.partition(":")
    return head if sep else title


def clean_title(text: object) -> str:
    """Whitespace, line breaks and wrapping quotes removed; nothing else changed."""
    if not isinstance(text, str):
        return ""
    t = " ".join(text.split())
    while len(t) >= 2 and t[0] in _QUOTES and t[-1] in _QUOTES and not any(q in t[1:-1] for q in _QUOTES):
        t = t[1:-1].strip()
    return t


def _is_emoji_char(ch: str) -> bool:
    code = ord(ch)
    if (0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF or 0x2300 <= code <= 0x23FF
            or 0x2B50 <= code <= 0x2B55 or code == 0x200D or 0xFE00 <= code <= 0xFE0F or code == 0x20E3):
        return True
    return unicodedata.category(ch) in ("So", "Sk")


def _has_emoji(text: str) -> bool:
    # Same test as video_engine.is_emoji_char: such a title is drawn as a
    # PNG instead of by libass, and the prompt bans emoji anyway.
    return any(_is_emoji_char(ch) for ch in text)


def title_problem(title: str) -> Optional[str]:
    """Why a cleaned title breaks the rules, or None when it is fine."""
    if not title:
        return "empty"
    words = title.split()
    if not words:
        # Whitespace only: clean_title() normally removes it before this,
        # but the check is public and must not raise on its own.
        return "empty"
    if len(words) > MAX_TITLE_WORDS:
        return f"{len(words)} words (max {MAX_TITLE_WORDS})"
    if len(title) > MAX_TITLE_CHARS:
        return f"{len(title)} characters (max {MAX_TITLE_CHARS})"
    longest = max(words, key=len)
    if len(longest) > MAX_TITLE_WORD_CHARS:
        return f"word {longest!r} has {len(longest)} characters (max {MAX_TITLE_WORD_CHARS})"
    if "#" in title:
        return "contains a hashtag"
    if _has_emoji(title):
        return "contains an emoji or symbol"
    if _FIRST_PERSON.search(_editor_voice(title)):
        return "first person (the editor is not the speaker)"
    return None


def _option_texts(options: object) -> List[object]:
    """Gemini's options as raw texts: [{"text": ...}], ["..."] or anything broken."""
    if not isinstance(options, (list, tuple)):
        return []
    texts = []
    for opt in options:
        if isinstance(opt, dict):
            texts.append(opt.get("text"))
        elif hasattr(opt, "text"):
            texts.append(getattr(opt, "text"))
        else:
            texts.append(opt)
    return texts


def _shorten(title: str) -> str:
    """
    Cut words off the end until the limits hold (last resort only). Words are
    never taken from the middle, which could change the meaning; a title with
    an over-long word therefore cannot be shortened and returns "".
    """
    words = title.split()[:MAX_TITLE_WORDS]
    while words and (len(" ".join(words)) > MAX_TITLE_CHARS or words[-1].lower().strip(",;:-") in _DANGLING):
        words.pop()
    short = " ".join(words).rstrip(",;:-")
    return short if short and title_problem(short) is None else ""


def pick_titles(
    options: object,
    legacy_title: object = "",
    legacy_suggestion: object = "",
    sanitize: Callable[[str], str] = lambda t: t,
    label: str = "clip",
    untitled: Optional[int] = None,
) -> Tuple[List[str], List[str]]:
    """
    Up to TITLE_OPTIONS valid titles, first = the active one, and the list of
    problems found (already logged). `sanitize` is the existing first-person
    fixer, applied before checking, as the old titles always were.

    `untitled` marks a clip the backend made itself (issue #98): it carries no
    title of its own by design, so the generic title is numbered with it and
    the missing options are not reported as a fault in Gemini's answer.
    """
    problems: List[str] = []
    picked: List[str] = []
    seen = set()

    def consider(raw: object, source: str) -> None:
        title = clean_title(sanitize(clean_title(raw)))
        reason = title_problem(title)
        if reason is None and title.casefold() in seen:
            reason = "duplicate"
        if reason:
            problems.append(f"{label}: {source} rejected ({reason}): {title!r}")
            return
        seen.add(title.casefold())
        picked.append(title)

    raw_options = _option_texts(options)
    if not raw_options and untitled is None:
        problems.append(f"{label}: no title options in Gemini's answer")
    for i, raw in enumerate(raw_options, start=1):
        if len(picked) >= TITLE_OPTIONS:
            problems.append(f"{label}: extra option {i} ignored (only {TITLE_OPTIONS} kept)")
            break
        consider(raw, f"option {i}")

    if not picked and untitled is None:
        # Fallback 1: the old single-title fields, if they meet the rules.
        for raw, source in ((legacy_suggestion, "title_suggestion"), (legacy_title, "title")):
            consider(raw, f"fallback {source}")
            if picked:
                break

    if not picked:
        # Fallback 2: the old title cut to fit, then a neutral generic title.
        # A backup clip skips straight to the generic title: it has no old
        # title, so reporting the empty fields as rejections would be noise.
        base = clean_title(sanitize(clean_title(legacy_suggestion) or clean_title(legacy_title)))
        short = _shorten(base) if untitled is None else ""
        if short:
            problems.append(f"{label}: using the old title shortened to fit: {short!r}")
            picked.append(short)
        else:
            if untitled is None:
                problems.append(f"{label}: no usable title; using the generic fallback")
            picked.append(generic_fallback(untitled))

    for p in problems:
        logger.warning(p)
    return picked, problems


def generic_fallback(number: Optional[int] = None) -> str:
    """GENERIC_FALLBACK, cut to the configured limits if they are stricter.

    With `number`, it is numbered (issue #98): backup clips all land on this
    title, and identical names in the Studio give the editor no way to tell
    the clips apart. The number is appended only while it still fits the
    rules, so stricter limits fall back to the plain title.
    """
    base = _shorten(GENERIC_FALLBACK) or "Momen Penting"
    if number is None:
        return base
    # The number is what tells two backup clips apart, so it is kept and the
    # words before it are dropped until the title fits. _shorten cuts from the
    # end, which would drop the number first, so the text is cut here instead.
    words = base.split()
    while words:
        # Never leave the text ending on a linking word ("Momen Penting dari 2").
        if words[-1].lower().strip(",;:-") not in _DANGLING:
            numbered = f"{' '.join(words)} {number}"
            if title_problem(numbered) is None:
                return numbered
        words.pop()
    return base


def prompt_rules() -> str:
    """The title rules for the Gemini prompt, built from the settings above."""
    n, w, c, l = TITLE_OPTIONS, MAX_TITLE_WORDS, MAX_TITLE_CHARS, MAX_TITLE_WORD_CHARS
    return (
        "HOOK TITLE RULES (Indonesian TikTok / YouTube Shorts / Instagram Reels):\n"
        "1. Write every title in casual, natural Indonesian as used on Indonesian TikTok, "
        "even when the video is in another language.\n"
        f"2. For each clip give exactly {n} options in \"title_options\", each with a different angle "
        "(for example: a question, a surprising statement, the situation/context, or the reaction/emotion). "
        "The first option is used by default, so make it the strongest. Put the angle in \"angle\".\n"
        f"3. HARD LENGTH LIMIT: each title has at most {w} words and at most {c} characters, and no word "
        f"longer than {l} characters. Count the words of every title before answering; if a title is too long, "
        "rewrite it shorter (drop filler words, keep the hook). The app discards any title over the limit, so "
        "an over-long title is wasted. No hashtags, no emoji, no quotation marks.\n"
        "4. Spark curiosity or emotion. Do NOT write like a news headline "
        "(avoid patterns like \"[Name] Jelaskan Bahaya ...\" or \"[Name] Explains ...\").\n"
        "5. Give just enough context that someone who has never seen the video understands the situation.\n"
        "6. If the speaker is a well-known or relevant figure, their name may open the title (e.g. \"dr. X: ...\").\n"
        "7. Be honest: the title must match what the clip really contains. No misleading clickbait.\n"
        "8. The title must be supported by what is said in the first 3-5 seconds after the clip's start_time. "
        "Do not promise something that only comes later or never comes.\n"
        "9. Match the style to the kind of content (funny, education/health, motivation, controversy, "
        "story, or whatever fits) and write that kind in \"content_type\".\n"
        "10. Never use first-person pronouns (I, me, my, saya, aku, gue, gw): the editor posting the clip "
        "is not the person speaking.\n"
        "11. Also copy the first option into \"title\".\n"
        "Patterns that work (use the idea, never copy the wording):\n"
        "- Question: \"dr. Tirta: Olahraga Berat Bisa Rusak Jantung?\"\n"
        "- Surprising statement: \"Ternyata Lari Tiap Hari Nggak Selalu Sehat\"\n"
        "- Situation: \"Host Nggak Nyangka Jawaban Tamunya Begini\"\n"
        "- Reaction: \"Satu Studio Langsung Diam Dengar Ini\"\n"
        "Bad (news headline): \"Dr. Tirta Jelaskan Bahaya Memaksa Jantung Bekerja Terlalu Keras\"\n"
    )

