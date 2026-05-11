from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _langs_to_text(languages: object) -> str:
    if languages is None:
        return ""
    if isinstance(languages, (list, tuple)):
        return " ".join(_norm(item) for item in languages)
    return _norm(languages)


@dataclass
class Speaker:
    enabled: bool = False
    preferred_voice_hints: tuple[str, ...] = field(default_factory=lambda: ("microsoft an", "vi-vn", "vietnamese", "vietnam"))
    _engine: object | None = field(default=None, init=False, repr=False)
    _voice_id: str | None = field(default=None, init=False, repr=False)

    def _ensure_engine(self) -> object | None:
        if self._engine is not None:
            return self._engine

        try:
            import pyttsx3
        except Exception:
            return None

        try:
            engine = pyttsx3.init()
            self._voice_id = self._select_voice(engine)
            if self._voice_id:
                engine.setProperty("voice", self._voice_id)
            self._engine = engine
            return self._engine
        except Exception:
            return None

    def _select_voice(self, engine: object) -> str | None:
        try:
            voices = engine.getProperty("voices")
        except Exception:
            return None

        best_score = -1
        best_voice_id: str | None = None
        hints = [_norm(hint) for hint in self.preferred_voice_hints]

        for voice in voices or []:
            name = _norm(getattr(voice, "name", ""))
            voice_id = _norm(getattr(voice, "id", ""))
            langs = _langs_to_text(getattr(voice, "languages", ""))
            blob = f"{name} {voice_id} {langs}"

            score = 0
            if "vi" in langs or "vi-vn" in blob:
                score += 120
            if "microsoft an" in blob:
                score += 80
            if "vietnamese" in blob or "vietnam" in blob:
                score += 40
            for hint in hints:
                if hint and hint in blob:
                    score += 20

            if score > best_score:
                best_score = score
                best_voice_id = str(getattr(voice, "id", "")) or None

        return best_voice_id if best_score > 0 else None

    def list_voices(self) -> list[dict[str, str]]:
        engine = self._ensure_engine()
        if engine is None:
            return []

        try:
            voices = engine.getProperty("voices")
        except Exception:
            return []

        items: list[dict[str, str]] = []
        for voice in voices or []:
            items.append(
                {
                    "id": str(getattr(voice, "id", "")),
                    "name": str(getattr(voice, "name", "")),
                    "languages": _langs_to_text(getattr(voice, "languages", "")),
                    "gender": str(getattr(voice, "gender", "")),
                    "selected": "true" if str(getattr(voice, "id", "")) == (self._voice_id or "") else "false",
                }
            )
        return items

    def speak_many(self, messages: list[str]) -> None:
        if not self.enabled:
            return

        if not messages:
            return

        engine = self._ensure_engine()
        if engine is None:
            return

        try:
            for msg in messages:
                if msg.strip():
                    engine.say(msg)
            engine.runAndWait()
        except Exception:
            return
