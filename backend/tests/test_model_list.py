"""Which Gemini models the analysis tries and /api/models lists (#74): both
use the same filter, so a model one of them skips the other skips too."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import routes_analyze  # noqa: E402


class Model:
    def __init__(self, name, actions=("generateContent",)):
        self.name = name
        self.supported_actions = list(actions)


MODELS = [
    Model("models/gemini-3.5-flash"), Model("models/gemini-3.5-flash-lite"),
    Model("models/gemini-3.5-flash-tts"),                     # speech, not text
    Model("models/gemini-2.5-pro"),
    Model("models/gemini-3.0-flash", ("embedContent",)),      # cannot write text
    Model("models/gemini-2.0-flash-thinking-exp"),            # excluded family
    Model("models/gemini-exp-1206"), Model("models/gemma-3-27b"),
    Model("models/gemini-3.5-flash"),                         # listed twice
    Model("models/text-embedding-004"),
    Model("models/gemini-1.5-pro", ()),                       # no actions listed: kept
    Model("models/gemini-2.5-flash-image"), Model(None),
    Model("models/gemini-3.6-pro-preview"), Model("models/gemini-live-2.5"),
]

KNOWN_FLASH = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.0-flash-lite",
               "gemini-1.5-flash", "gemini-1.5-flash-8b"]


class FakeClient:
    listing = MODELS

    def __init__(self, *args, **kwargs):
        self.models = self

    def list(self):
        if isinstance(FakeClient.listing, Exception):
            raise FakeClient.listing
        return iter(FakeClient.listing)


def test_the_analysis_tries_every_flash_model_that_writes_text_newest_first():
    FakeClient.listing = MODELS
    assert routes_analyze.get_flash_models_for_key(FakeClient()) == [
        "gemini-3.5-flash", "gemini-3.5-flash-lite", *KNOWN_FLASH]


def test_the_model_list_has_flash_then_pro_then_the_rest(monkeypatch):
    FakeClient.listing = MODELS
    monkeypatch.setattr(routes_analyze.genai, "Client", FakeClient)
    assert routes_analyze._list_models_for_key("key", ["default"])["models"] == [
        "gemini-3.5-flash", "gemini-3.5-flash-lite", *KNOWN_FLASH,
        "gemini-3.6-pro-preview", "gemini-2.5-pro", "gemini-1.5-pro", "gemini-exp-1206"]


def test_without_a_listing_the_known_flash_models_are_still_tried():
    FakeClient.listing = RuntimeError("503 UNAVAILABLE")
    assert routes_analyze.get_flash_models_for_key(FakeClient()) == KNOWN_FLASH
