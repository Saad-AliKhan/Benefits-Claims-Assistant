# -*- coding: utf-8 -*-
"""Indic-Transcribe Core wiring (voice_core/indic.py), spoken numbers and the silence guard.

The real model (4.6 GB, gated) is not needed: a fake engine stands in for it. What the model itself hears is
measured on the laptop with tools/voice/compare_asr.py --models indic turbo.
"""
import numpy as np
import pytest

import voice_core
from voice_core import indic
from urdu_intent.numbers import spoken_digits


# ---- spoken numbers -> digits (the model writes numbers as words)
@pytest.mark.parametrize("said, want", [
    ("تین پانچ دو صفر دو ایک دو تین چار پانچ چھ سات ایک", "3520212345671"),
    ("پینتیس دو سو دو", "35202"),
    ("بارہ سو چونتیس", "1234"),
    ("میرا نمبر صفر تین صفر صفر ایک دو تین چار پانچ چھ سات ہے", "میرا نمبر 03001234567 ہے"),
    ("مجھے پچیس ہزار روپے ملیں گے", "مجھے 25000 روپے ملیں گے"),
    ("دو ہزار پچیس میں", "2025 میں"),
    ("دو ہزار دو سو پانچ", "2205"),
    ("three five two zero two", "35202"),
    ("۳۵۲۰۲ ایک دو", "3520212"),
])
def test_spoken_digits(said, want):
    assert spoken_digits(said) == want


@pytest.mark.parametrize("said", ["ایک افسر سے بات کرنی ہے", "میری تین بیٹیاں ہیں", "دو", "مجھے پیسے کب ملیں گے",
                                  "نو"])  # one number word alone stays a word ('ایک' = 'a', 'نو' also = 'no/nine')
def test_single_number_words_untouched(said):
    assert spoken_digits(said) == said


def test_cnic_said_as_words():
    from app.agent import digits_cnic
    assert digits_cnic("میرا شناختی کارڈ تین پانچ دو صفر دو ایک دو تین چار پانچ چھ سات ایک ہے") == "35202-1234567-1"
    assert digits_cnic("پینتیس دو سو دو، بارہ سو چونتیس پانچ چھ سات، ایک") == "35202-1234567-1"
    assert digits_cnic("ایک افسر") is None


# ---- model names and folders
def test_names():
    for n in ("indic", "indic-onnx", "indic-core", "INDIC", "models/indic-transcribe-core"):
        assert indic.is_indic(n), n
    for n in ("small", "turbo", "large-v3-turbo", "", None):
        assert not indic.is_indic(n), n


def test_missing_model_says_what_to_do(monkeypatch, tmp_path):
    monkeypatch.setattr(indic, "FOLDERS", {"pytorch": tmp_path / "a", "onnx": tmp_path / "b"})
    with pytest.raises(indic.IndicMissing, match="fetch_indic.py"):
        indic.find("indic")


def test_find_prefers_official_then_onnx(monkeypatch, tmp_path):
    pt, ox = tmp_path / "pt", tmp_path / "ox"
    ox.mkdir()
    (ox / "encoder-model.onnx").write_bytes(b"x")
    monkeypatch.setattr(indic, "FOLDERS", {"pytorch": pt, "onnx": ox})
    assert indic.find("indic") == ("onnx", ox)          # only the ONNX one is downloaded
    pt.mkdir()
    (pt / "model.safetensors").write_bytes(b"x")
    assert indic.find("indic") == ("pytorch", pt)
    assert indic.find("indic-onnx") == ("onnx", ox)
    assert indic.find(str(ox)) == ("onnx", ox)          # a folder path


def test_text_from_any_output_shape():
    assert indic._text("سلام") == "سلام"
    assert indic._text({"text": " سلام "}) == "سلام"
    assert indic._text([{"text": "میری"}, "درخواست"]) == "میری درخواست"


# ---- transcribe() with a fake Indic engine
class FakeIndic(indic.IndicEngine):
    def __init__(self, says: str):          # no model files
        self.says, self.calls, self.name = says, [], "fake"

    def transcribe(self, audio, language="ur"):
        self.calls.append((len(audio), language))
        return self.says


def _use(monkeypatch, engine, spans):
    monkeypatch.setattr(voice_core, "load_model", lambda name=None: engine)
    monkeypatch.setattr(voice_core, "speech_spans", lambda audio: spans)


def _audio(seconds=3.0, level=0.1):
    t = np.arange(int(16000 * seconds)) / 16000
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_speech_is_sent_with_language_and_numbers_become_digits(monkeypatch):
    eng = FakeIndic("میرا نمبر تین پانچ دو صفر دو ہے")
    _use(monkeypatch, eng, [{"start": 8000, "end": 40000}])
    out = voice_core.transcribe(_audio(), language="ur")
    assert out["text"] == "میرا نمبر 35202 ہے" and out["quality"] == "ok"
    assert eng.calls == [(32000, "ur")]       # only the part with speech, in Urdu (never auto-detect)


def test_no_speech_means_the_model_is_not_asked(monkeypatch):
    eng = FakeIndic("اچھا")                    # what it would 'hear' in silence
    _use(monkeypatch, eng, [])
    out = voice_core.transcribe(_audio(level=0.001))
    assert out["text"] == "" and out["quality"] == "silent" and eng.calls == []
    out = voice_core.transcribe(_audio(level=0.3))        # loud sound, no speech -> ask for a quieter place
    assert out["text"] == "" and out["quality"] == "noisy"


def test_a_blip_is_not_speech(monkeypatch):
    eng = FakeIndic("شکریہ")
    _use(monkeypatch, eng, [{"start": 1000, "end": 3000}])   # 0.125 s
    assert voice_core.transcribe(_audio())["text"] == ""
    assert eng.calls == []


def test_short_real_answers_are_kept(monkeypatch):
    for word in ("جی", "ہاں", "نہیں"):
        eng = FakeIndic(word)
        _use(monkeypatch, eng, [{"start": 4000, "end": 12000}])  # 0.5 s
        assert voice_core.transcribe(_audio())["text"] == word


def test_whisper_noise_words_still_caught(monkeypatch):
    eng = FakeIndic("ناظرین subscribe")
    _use(monkeypatch, eng, [{"start": 0, "end": 40000}])
    assert voice_core.transcribe(_audio())["quality"] == "noisy"


def test_silence_filler_rule():
    assert voice_core.silence_filler("اچھا", 0.1, 0.0)
    assert voice_core.silence_filler("شکریہ", 2.0, 0.9)
    assert not voice_core.silence_filler("شکریہ", 2.0, 0.1)
    assert not voice_core.silence_filler("جی", 0.6, 0.9)
    assert not voice_core.silence_filler("", 0.0, 1.0)


# ---- the app falls back to Whisper when Indic cannot start
def test_fallback_to_whisper(monkeypatch):
    from app import ai_engines
    from app.config import settings
    monkeypatch.setattr(settings, "whisper_model", "indic")
    monkeypatch.setattr(settings, "whisper_fallback", "turbo")
    loaded = []

    def fake_load(name=None):
        if indic.is_indic(name):
            raise indic.IndicMissing("not downloaded")
        loaded.append(name)
        return object()
    monkeypatch.setattr(voice_core, "load_model", fake_load)
    monkeypatch.setattr(voice_core, "MODEL_NAME", "small")
    monkeypatch.setattr(ai_engines, "_state", dict(ai_engines._state, voice_ready=False, voice_error=None,
                                                   voice_model=None, voice_note=None))
    ai_engines._load_voice()
    st = ai_engines._state
    assert st["voice_ready"] and st["voice_model"] == "turbo" and loaded == ["turbo"]
    assert "not downloaded" in st["voice_note"] and voice_core.MODEL_NAME == "turbo"
    assert ai_engines.status()["voice"]["whisper_model"] == "turbo"
