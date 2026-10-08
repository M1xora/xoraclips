"""
The steps of an analysis that need no network, thread or web framework
(#74): the schemas, the search range, heatmap engagement per line, the
Gemini prompt, reading Gemini's answer, backup clips when it finds none,
and finishing the clips (snapping, lengths, titles, hashtags). /api/analyze
in routes_analyze.py runs these in order and streams progress.
"""
import json
import logging
import math
import re
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

try:
    from backend import clip_bounds, clip_lengths, title_rules
except ImportError:
    import clip_bounds
    import clip_lengths
    import title_rules

logger = logging.getLogger("xoraclips")


class ViralClip(BaseModel):
    title: str = Field(description="Catchy clip title, max 8 words. MUST NEVER use first-person pronouns ('I', 'me', 'my', 'saya', 'aku'). Attribute to the speaker/host by name, role, or use objective framing.")
    start_time: float = Field(description="Clip start in seconds, aligned to a sentence boundary")
    end_time: float = Field(description="Clip end in seconds, aligned to a sentence boundary")
    hook_time: float = Field(description="Absolute timestamp in seconds from video start where the potential hook occurs inside this clip range (must be >= start_time and <= end_time)")
    virality_score: int = Field(description="Virality score 1-100")
    key_quotes: List[str] = Field(description="1-2 key quotes from the clip")
    transcript: str = Field(description="Spoken text of the clip")
    title_suggestion: str = Field(default="", description="Catchy alternative title suggestion. MUST NEVER use first-person pronouns ('I', 'me', 'my'). Attribute to speaker or objective topic.")
    caption_suggestion: str = Field(default="", description="Engaging social media caption suggestion attributing quotes or insights to the speaker.")
    hashtag_suggestion: str = Field(default="", description="Relevant hashtags suggestion (e.g. #hashtag1 #hashtag2)")
    # Issue #31: the checked hook titles, first = active (also in title and
    # title_suggestion). Empty for analyses made before this change.
    title_options: List[str] = Field(default_factory=list, description="Up to 3 hook titles; the first is the active one")
    content_type: str = Field(default="", description="Kind of content Gemini saw, e.g. lucu, edukasi, motivasi")


class TitleOption(BaseModel):
    text: str = Field(description="One hook title in casual Indonesian, following the HOOK TITLE RULES in the prompt")
    angle: str = Field(default="", description="The approach of this title: question, surprising statement, situation, reaction, or another")


class ViralClipGemini(BaseModel):
    title: str = Field(description="Same text as the first entry of title_options (a hook title in casual Indonesian). NEVER first-person ('I', 'me', 'my', 'saya', 'aku', 'gue').")
    start_time: float = Field(description="Clip start in seconds, aligned to a sentence boundary")
    end_time: float = Field(description="Clip end in seconds, aligned to a sentence boundary")
    hook_time: float = Field(description="Absolute timestamp in seconds from video start where the potential hook occurs inside this clip range (must be >= start_time and <= end_time)")
    virality_score: int = Field(description="Virality score 1-100")
    key_quotes: List[str] = Field(description="1-2 key quotes from the clip")
    title_suggestion: str = Field(default="", description="Leave empty: alternative titles go in title_options.")
    caption_suggestion: str = Field(default="", description="Engaging social media caption suggestion attributing insights or story to the speaker.")
    hashtag_suggestion: str = Field(default="", description="Relevant hashtags suggestion (e.g. #hashtag1 #hashtag2)")
    title_options: List[TitleOption] = Field(description="Exactly the number of hook titles the HOOK TITLE RULES ask for, strongest first, each with a different angle")
    content_type: str = Field(default="", description="Kind of content in this clip, e.g. lucu, edukasi/kesehatan, motivasi, kontroversi, cerita")


class VideoAnalysis(BaseModel):
    summary: str = Field(description="1-2 sentence video summary, followed by 2-4 general hashtags (e.g. #podcast #marriage #success)")
    clips: List[ViralClipGemini] = Field(description="List of viral clip candidates, sorted by virality_score desc")


class HeatmapPoint(BaseModel):
    start_time: float
    end_time: float
    value: float


class TranscriptLine(BaseModel):
    start: float
    end: float
    text: str
    engagement: Optional[float] = None


class AnalyzeResponse(BaseModel):
    video_id: str
    title: str
    channel: Optional[str] = None
    duration: float
    heatmap: List[HeatmapPoint]
    summary: str
    clips: List[ViralClip]
    transcript: Optional[List[TranscriptLine]] = None
    model: Optional[str] = None
    # Issue #94: (shortest, longest) of the chosen preset, so the clip cards
    # can mark a clip that fell outside it. Clips are never cut to fit; an
    # analysis made before this change has no range and shows no mark.
    clip_range_seconds: Optional[Tuple[int, int]] = None
    # The preset's own label ("30s", "2m"), so the card can name what was asked for.
    clip_range_preset: Optional[str] = None


class AnalysisError(Exception):
    """A request the analysis cannot answer; becomes an error event."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def lowercase_hashtags_in_string(text: str) -> str:
    """Finds all hashtags (#word) in a string and converts them to lowercase."""
    if not text:
        return text
    return re.sub(r'#\w+', lambda m: m.group(0).lower(), text)


def sanitize_first_person_title(title: str, speaker_or_channel: str = "") -> str:
    """
    Sanitizes accidental first-person perspective ('I', 'Me', 'My', 'Saya', 'Aku', 'Gue')
    from generated clip titles and title suggestions, replacing them with speaker or channel attribution,
    or objective framing so titles never appear as the user's personal opinion.
    """
    if not title:
        return title
    t = title.strip()
    speaker = speaker_or_channel.strip() if speaker_or_channel else ""
    subject = speaker if speaker else "The Speaker"

    # 1. English Why / How / What / When / Where
    t = re.sub(r"^why\s+i\s+think\b", f"{subject} Explains Why", t, flags=re.IGNORECASE)
    t = re.sub(r"^why\s+i\s+believe\b", f"{subject} Explains Why", t, flags=re.IGNORECASE)
    t = re.sub(r"^why\s+i\s+", f"Why {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^how\s+i\s+", f"How {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^what\s+i\s+think\b", f"{subject}'s Thoughts On", t, flags=re.IGNORECASE)
    t = re.sub(r"^what\s+i\s+learned\b", f"What {subject} Learned", t, flags=re.IGNORECASE)
    t = re.sub(r"^what\s+i\s+", f"What {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^when\s+i\s+", f"When {subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^where\s+i\s+", f"Where {subject} ", t, flags=re.IGNORECASE)

    # 2. English My [Noun] (e.g. My Opinion, My Story, My Regret)
    t = re.sub(r"^my\s+([a-zA-Z]+)", lambda m: f"{subject}'s {m.group(1)}" if speaker else f"The {m.group(1)}", t, flags=re.IGNORECASE)

    # 3. English First-person action verbs (e.g. I Tried, I Discovered, I Built)
    t = re.sub(r"^i\s+(tried|found|made|discovered|bought|quit|lost|learned|realized|spent|built|saw|went|started|joined|left|hate|love)\b", rf"{subject} \1", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+was\b", f"{subject} Was", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+am\b", f"{subject} Is", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+have\b", f"{subject} Has", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+had\b", f"{subject} Had", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+got\b", f"{subject} Got", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+think\b", f"{subject} Thinks", t, flags=re.IGNORECASE)
    t = re.sub(r"^i\s+believe\b", f"{subject} Believes", t, flags=re.IGNORECASE)

    # 4. Indonesian / Malay first-person replacements (Saya, Aku, Gue, Gw)
    indo_subject = speaker if speaker else "Host"
    t = re.sub(r"^(kenapa|mengapa)\s+(saya|aku|gue|gw)\s+", rf"\1 {indo_subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^(cara|bagaimana)\s+(saya|aku|gue|gw)\s+", rf"Cara {indo_subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^(alasan)\s+(saya|aku|gue|gw)\s+", rf"Alasan {indo_subject} ", t, flags=re.IGNORECASE)
    t = re.sub(r"^(saya|aku|gue|gw)\s+(mencoba|menemukan|membuat|yakin|berpikir|menyesal|kehilangan|belajar|mulai|berhenti)\b", rf"{indo_subject} \2", t, flags=re.IGNORECASE)
    t = re.sub(r"^(pendapat|opini)\s+(saya|aku|gue|gw)\b", rf"Opini {indo_subject}", t, flags=re.IGNORECASE)

    return t.strip()


def get_average_heatmap_value(start: float, end: float, heatmap: List[dict]) -> float:
    """Calculates the average retention score from the heatmap for a transcript time segment."""
    if not heatmap:
        return 0.0

    overlaps = []
    for point in heatmap:
        p_start = point.get('start_time', 0.0)
        p_end = point.get('end_time', 0.0)
        p_val = point.get('value', 0.0)

        # Check if heatmap point overlaps with transcript segment
        if max(start, p_start) < min(end, p_end):
            overlaps.append(p_val)

    if overlaps:
        return sum(overlaps) / len(overlaps)

    # Fallback to closest point if no direct overlap matches
    closest_val = 0.0
    min_dist = float('inf')
    mid_time = (start + end) / 2.0
    for point in heatmap:
        p_mid = (point.get('start_time', 0.0) + point.get('end_time', 0.0)) / 2.0
        dist = abs(p_mid - mid_time)
        if dist < min_dist:
            min_dist = dist
            closest_val = point.get('value', 0.0)
    return closest_val


# --- transcript ---------------------------------------------------------------------------

def estimate_duration(duration: float, transcript_lines: List[dict]) -> float:
    """The video's duration, or the end of the last caption line when it is unknown."""
    if duration == 0.0 and transcript_lines:
        last = transcript_lines[-1]
        return last.get("start", 0.0) + last.get("duration", 0.0)
    return duration


def apply_range(transcript_lines: List[dict], duration: float, range_start: Optional[float],
                range_end: Optional[float]) -> Tuple[List[dict], float, float, float]:
    """Keeps the lines inside the searched range. Returns the lines, the range's
    start and end, and the duration (the range's length when one is set)."""
    start_bound = 0.0
    end_bound = duration
    if range_start is None and range_end is None:
        return transcript_lines, start_bound, end_bound, duration

    start_bound = range_start if range_start is not None else 0.0
    end_bound = range_end if range_end is not None else duration
    if start_bound < 0.0:
        start_bound = 0.0
    if end_bound > duration:
        end_bound = duration
    if start_bound >= end_bound:
        raise AnalysisError("Invalid search range: start time must be less than end time.")

    filtered_lines = []
    for line in transcript_lines:
        ls = line.get("start", 0.0)
        le = ls + line.get("duration", 0.0)
        if max(ls, start_bound) < min(le, end_bound):
            filtered_lines.append(line)
    if not filtered_lines:
        raise AnalysisError(f"No subtitles found in the specified range {start_bound}s to {end_bound}s.")

    duration = end_bound - start_bound
    logger.info(f"Filtered transcript to custom range: {start_bound}s to {end_bound}s (duration: {duration}s)")
    return filtered_lines, start_bound, end_bound, duration


def enrich_transcript(transcript_lines: List[dict], heatmap: List[dict]) -> List[dict]:
    """Caption lines as start/end/text with the heatmap's audience interest for each."""
    enriched_transcript = []
    for line in transcript_lines:
        ls   = line.get("start", 0.0)
        ld   = line.get("duration", 0.0)
        le   = ls + ld
        score = get_average_heatmap_value(ls, le, heatmap)
        enriched_transcript.append({
            "start":      round(ls, 2),
            "end":        round(le, 2),
            "text":       line.get("text", ""),
            "engagement": round(score, 3)
        })
    return enriched_transcript


# --- prompt -------------------------------------------------------------------------------

def build_prompt(enriched_transcript: List[dict], *, heatmap: List[dict], title: str, channel: str,
                 start_bound: float, end_bound: float, duration: float, clip_duration: str,
                 clip_range: str, custom_prompt: Optional[str], is_long_video: bool) -> Tuple[str, int]:
    """The prompt for Gemini, and how many transcript lines it carries (long
    transcripts are cut)."""
    transcript_dump = []
    for line in enriched_transcript:
        eng = f"|{line['engagement']:.2f}" if heatmap and line['engagement'] > 0 else ""
        transcript_dump.append(f"{line['start']:.1f}|{line['end']:.1f}{eng} {line['text']}")

    MAX_LINES = 2500 if is_long_video else 800
    if len(transcript_dump) > MAX_LINES:
        logger.warning(f"Transcript {len(transcript_dump)} lines — truncating to {MAX_LINES}.")
        transcript_dump = transcript_dump[:MAX_LINES]

    transcript_text = "\n".join(transcript_dump)
    dur_range   = clip_lengths.prompt_range(clip_duration)
    heatmap_note = (
        "Columns: start|end|audience_interest(0-1). Prioritise high-interest peaks."
        if heatmap else
        "No audience interest data. Use content hooks, energy, and story arcs."
    )
    focus_instruction = ""
    if custom_prompt and custom_prompt.strip():
        focus_instruction = f"CRITICAL FOCUS: The user specifically wants you to find clips matching the following query/theme: \"{custom_prompt.strip()}\". Prioritize and tailor your selection of viral clips to fit this request, while still ensuring they make good standalone clips.\n\n"

    channel_context = f"- Channel / Host / Creator: {channel}\n" if channel else ""

    prompt = (
        f"You are an expert viral video clip editor finding top clip candidates for TikTok, Instagram Reels, and YouTube Shorts.\n"
        f"Analyze this YouTube video transcript and find {clip_range} high-performing, standalone clip candidates.\n\n"
        f"VIDEO CONTEXT:\n"
        f"- Video Title: {title}\n"
        f"{channel_context}"
        f"- Video Duration: {int(start_bound)}s to {int(end_bound)}s (Total: {int(duration)}s) | Target clip length: {dur_range}\n"
        f"- Heatmap: {heatmap_note}\n\n"
        f"{focus_instruction}"
        f"{clip_lengths.prompt_rules(clip_duration)}"
        f"{title_rules.prompt_rules()}"
        f"Write caption_suggestion, key_quotes and hashtag_suggestion in the language of the transcript.\n\n"
        f"Transcript (start|end[|interest] text):\n---\n{transcript_text}\n---\n\n"
        f"Rules: use exact seconds from transcript; clips must start/end at sentence boundaries; do not overlap.\n"
        f"Return {clip_range} clips sorted by virality_score desc."
    )
    return prompt, len(transcript_dump)


def pick_model(requested: Optional[str]) -> str:
    """The model the user asked for; retired families become gemini-2.5-flash."""
    requested_model = (requested or 'gemini-2.5-flash').strip()
    if any(dep in requested_model.lower() for dep in ['gemini-1.0', 'gemini-pro-vision']):
        logger.info(f"Requested model '{requested_model}' is outdated. Upgrading to gemini-2.5-flash.")
        requested_model = 'gemini-2.5-flash'
    return requested_model


def waiting_stage(elapsed: int, n_lines: int, model_name: str, clip_range: str) -> Tuple[str, str, int]:
    """What the progress bar says while Gemini works: stage, detail and step
    progress for the seconds waited so far. Gemini reports nothing while it
    works, so these follow the clock, not the model."""
    if elapsed < 5:
        stage = "Neural Context Loading"
        detail = f"Transmitting {n_lines} timestamped dialogue segments to {model_name}..."
        step_prog = min(35, 12 + elapsed * 4)
    elif elapsed < 12:
        stage = "Retention Spike Cross-Analysis"
        detail = "Correlating viewer retention peaks against speaker dialogue to isolate viral moments..."
        step_prog = min(55, 35 + int((elapsed - 5) * 3))
    elif elapsed < 20:
        stage = "Viral Hook & Curiosity Detection"
        detail = "Scanning transcript dialogue for opening hooks, punchlines, controversial takes & emotional peaks..."
        step_prog = min(72, 55 + int((elapsed - 12) * 2.2))
    elif elapsed < 30:
        stage = "Coherence & Sentence Boundary Snapping"
        detail = "Ensuring clip candidates start and end naturally on sentence boundaries without mid-word cuts..."
        step_prog = min(85, 72 + int((elapsed - 20) * 1.3))
    elif elapsed < 42:
        stage = "Virality Scoring & Selection"
        detail = f"Calculating virality coefficients (1-100) and selecting the top {clip_range} highest potential clips..."
        step_prog = min(92, 85 + int((elapsed - 30) * 0.7))
    else:
        stage = "Social Media Metadata Synthesis"
        detail = f"Drafting attention-grabbing titles, social captions, and targeted hashtags ({elapsed}s)..."
        step_prog = min(95, 92 + min(3, int((elapsed - 42) * 0.3)))
    return stage, detail, step_prog


# --- Gemini's answer ----------------------------------------------------------------------

def _number(value, default=None):
    """A finite number from a number or numeric text, else default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _text(value) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


# The field types come from the schema Gemini is asked to follow, so a new
# field is cleaned without a second list to keep in step.
_GEMINI_FIELDS = ViralClipGemini.model_fields
TEXT_FIELDS = tuple(n for n, f in _GEMINI_FIELDS.items() if f.annotation is str)
NUMBER_FIELDS = tuple(n for n, f in _GEMINI_FIELDS.items() if f.annotation in (int, float))
TEXT_LIST_FIELDS = tuple(n for n, f in _GEMINI_FIELDS.items() if f.annotation == List[str])
OPTIONAL_NUMBERS = ("hook_time",)   # None when missing: the clip's start is used


def _clean_clip(raw: dict) -> dict:
    # is_fallback marks the backend's own backup clips (finish_clips gives
    # them the numbered generic title). Dropping it here is what stops Gemini
    # from passing its own clips off as backup ones; the backup clips the
    # backend makes never pass through here and keep the flag until
    # finish_clips, which reads it and builds a ViralClip without it.
    clip = {k: v for k, v in raw.items() if k != "is_fallback"}
    for name in NUMBER_FIELDS:
        number = _number(raw.get(name), None if name in OPTIONAL_NUMBERS else 0.0)
        if number is not None and _GEMINI_FIELDS[name].annotation is int:
            number = int(number)
        clip[name] = number
    for name in TEXT_LIST_FIELDS:
        value = raw.get(name)
        if isinstance(value, list):
            clip[name] = [_text(v) for v in value if v is not None]
        else:
            clip[name] = [value] if isinstance(value, str) and value else []
    for name in TEXT_FIELDS:
        if name in raw:
            clip[name] = _text(raw[name])
    return clip


def clean_answer(parsed_data, model_name: str) -> Optional[dict]:
    """Gemini's answer with every field the type the rest of the analysis
    expects: numbers from numeric text, text from anything else, a missing or
    unreadable hook as None, entries that are not clips dropped. None when
    the answer is unreadable: not a JSON object, clips that are not a list,
    or only entries that are not clips. JSON mode makes a wrong type rare,
    but one used to break the stream without an error (#74)."""
    if not isinstance(parsed_data, dict):
        if parsed_data is not None:
            logger.warning(f"{model_name} answered with a JSON {type(parsed_data).__name__}, not an object.")
        return None
    raw_clips = parsed_data.get("clips", [])
    if not isinstance(raw_clips, list):
        logger.warning(f"{model_name} answered with clips that are not a list.")
        return None
    clips = [_clean_clip(raw) for raw in raw_clips if isinstance(raw, dict)]
    if raw_clips and not clips:
        logger.warning(f"{model_name} answered with {len(raw_clips)} clip(s), none of them readable.")
        return None
    return {**parsed_data, "summary": _text(parsed_data.get("summary")), "clips": clips}


def parse_gemini_answer(resp_candidate, model_name: str):
    """Gemini's answer as plain data (see clean_answer): the SDK's parsed
    object when it made one, else the JSON text (code fences removed). None
    when unreadable."""
    parsed_data = None
    if hasattr(resp_candidate, 'parsed') and resp_candidate.parsed is not None:
        parsed = resp_candidate.parsed
        parsed_data = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
    elif resp_candidate.text:
        raw_text = resp_candidate.text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)
        try:
            parsed_data = json.loads(raw_text)
        except Exception as json_err:
            logger.warning(f"JSON parsing error from {model_name}: {json_err}")
            parsed_data = None
    return clean_answer(parsed_data, model_name)


def backup_clips(enriched_transcript: List[dict], clip_duration: str, start_bound: float,
                 end_bound: float) -> List[dict]:
    """Clips around the moments with the most audience interest, for when no
    model found any."""
    logger.info("Generating fallback clips from heatmap and transcript segments...")
    sorted_lines = sorted(enriched_transcript, key=lambda l: l.get('engagement', 0.0), reverse=True)
    # Issue #34: windows around the peaks that do not overlap and stay
    # inside the searched range (end_bound, not the range's length).
    windows = clip_lengths.backup_windows(
        [l['start'] for l in sorted_lines], clip_duration, start_bound, end_bound)

    fallback_clips_list = []
    for i, (st, et, peak) in enumerate(windows):
        seg_lines = [l['text'] for l in enriched_transcript if max(l['start'], st) < min(l['end'], et)]
        seg_text = " ".join(seg_lines).strip()
        preview = seg_text[:60] + "..." if len(seg_text) > 60 else seg_text or f"Momen Pilihan {i+1}"
        fallback_clips_list.append({
            # Issue #98: no title here. These clips go through the same
            # title_rules check as Gemini's; with no options and no old title
            # they get the numbered Indonesian generic title. The caption is
            # Indonesian too: it is the text the editor copies when posting.
            "start_time": st,
            "end_time": et,
            "hook_time": peak,
            "virality_score": max(70, int(95 - i * 5)),
            "key_quotes": [seg_text[:80]] if seg_text else [],
            "caption_suggestion": f"Momen pilihan dari video: {preview} #viral #trending",
            "hashtag_suggestion": "#viral #shorts #trending",
            "is_fallback": True,
        })
    return fallback_clips_list


# --- finishing ----------------------------------------------------------------------------

def fit_bounds(raw_clips: List[dict], enriched_transcript: List[dict], clip_duration: str,
               start_bound: float, end_bound: float) -> List[Tuple[float, float]]:
    """Each clip's start and end on transcript line edges, widened to the
    minimum length and cut to the maximum."""
    # Issue #35: move clip starts/ends to transcript line edges (and, when
    # the transcript has punctuation, the end to the next sentence end)
    # so a clip does not open or close mid-line.
    raw_bounds = [(_number(c.get('start_time'), 0.0), _number(c.get('end_time'), 0.0)) for c in raw_clips]
    lines_index = clip_bounds.Lines(enriched_transcript)
    snapped_bounds = clip_bounds.snap_clips(
        raw_bounds, enriched_transcript, start_bound, end_bound, lines=lines_index)
    moved = sum(1 for r, s in zip(raw_bounds, snapped_bounds) if r != s)
    logger.info(f"Clip bounds: {moved}/{len(raw_bounds)} clip(s) moved to line/sentence edges.")
    # Issue #38: 2m/3m clips Gemini made too short are widened to the minimum.
    stretched = clip_lengths.stretch_short_clips(
        snapped_bounds, lines_index, clip_duration, start_bound, end_bound)
    widened = sum(1 for a, b in zip(snapped_bounds, stretched) if a != b)
    short = clip_lengths.still_short(stretched, clip_duration)
    if widened or short:
        logger.info(f"Clip length: {widened} clip(s) widened toward the {clip_lengths.label(clip_duration)} "
                    f"minimum; {short} still under it (no room next to other clips).")
    # Issue #34: the length limit runs after snapping, which can lengthen a clip.
    capped_bounds = [(s, clip_lengths.cap_length(s, e, lines_index, end_bound)) for s, e in stretched]
    cut = sum(1 for a, b in zip(stretched, capped_bounds) if a != b)
    if cut:
        logger.info(f"Clip length: {cut} clip(s) cut back to {clip_lengths.MAX_CLIP_SECONDS:.0f}s.")
    return capped_bounds


def finish_clips(raw_clips: List[dict], enriched_transcript: List[dict], clip_duration: str,
                 start_bound: float, end_bound: float, channel: str) -> List[ViralClip]:
    """Gemini's clips (or backup clips) as ViralClips: fitted bounds, the hook
    inside the clip, the clip's own transcript, checked titles, lowercase
    hashtags."""
    bounds = fit_bounds(raw_clips, enriched_transcript, clip_duration, start_bound, end_bound)
    final_clips = []
    for clip_no, raw_clip in enumerate(raw_clips, start=1):
        start, end = bounds[clip_no - 1]
        hook  = raw_clip.get('hook_time')
        if hook is None or not (start <= hook <= end):
            hook = start

        clip_lines = [
            line.get("text", "")
            for line in enriched_transcript
            if max(line.get("start", 0.0), start) < min(line.get("end", 0.0), end)
        ]

        # Ensure hashtags are always lowercase
        caption_sug = lowercase_hashtags_in_string(raw_clip.get('caption_suggestion', ''))
        hashtag_sug = lowercase_hashtags_in_string(raw_clip.get('hashtag_suggestion', ''))

        # Issue #31: every title Gemini wrote is checked against the rules;
        # rejections are logged and a safe fallback keeps the clip usable.
        # Issue #98: the backend's own backup clips go through this too, so
        # no clip can reach the Studio with an unchecked title. They carry no
        # title of their own, so they get the numbered generic one.
        titles, _ = title_rules.pick_titles(
            raw_clip.get('title_options'),
            legacy_title=raw_clip.get('title', ''),
            legacy_suggestion=raw_clip.get('title_suggestion', ''),
            sanitize=lambda t: sanitize_first_person_title(t, channel),
            label=f"clip {clip_no} ({start:.1f}-{end:.1f}s)",
            untitled=clip_no if raw_clip.get('is_fallback') else None,
        )
        clip_title = clip_suggestion = titles[0]

        final_clips.append(ViralClip(
            title=clip_title,
            start_time=start,
            end_time=end,
            hook_time=hook,
            virality_score=raw_clip.get('virality_score', 0),
            key_quotes=raw_clip.get('key_quotes') or [],
            transcript=" ".join(clip_lines),
            title_suggestion=clip_suggestion,
            caption_suggestion=caption_sug,
            hashtag_suggestion=hashtag_sug,
            title_options=titles,
            content_type=str(raw_clip.get('content_type') or ''),
        ))
    return final_clips


def heatmap_points(heatmap: List[dict]) -> List[HeatmapPoint]:
    return [
        HeatmapPoint(
            start_time=float(pt.get('start_time', 0.0)),
            end_time=float(pt.get('end_time', 0.0)),
            value=float(pt.get('value', 0.0))
        )
        for pt in (heatmap or [])
    ]


def build_response(*, video_id: str, title: str, channel: str, duration: float, heatmap: List[dict],
                   summary: str, clips: List[ViralClip], enriched_transcript: List[dict],
                   model: str, clip_duration: Optional[str] = None) -> AnalyzeResponse:
    """The final result: hashtags in the summary lowercase, the whole
    transcript with its engagement for the Studio."""
    response_transcript = [
        TranscriptLine(
            start=float(line["start"]),
            end=float(line["end"]),
            text=line["text"],
            engagement=line.get("engagement")
        )
        for line in enriched_transcript
    ]
    return AnalyzeResponse(
        video_id=video_id,
        title=title,
        channel=channel,
        duration=duration,
        heatmap=heatmap_points(heatmap),
        # Ensure hashtags are lowercase in the overall summary
        summary=lowercase_hashtags_in_string(summary),
        clips=clips,
        transcript=response_transcript,
        model=model,
        clip_range_seconds=clip_lengths.range_for(clip_duration) if clip_duration else None,
        clip_range_preset=clip_lengths.label(clip_duration) if clip_duration else None,
    )
