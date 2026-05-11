from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import ExerciseTemplate, FeatureFrame


@dataclass(slots=True)
class TemplateProfile:
    """Compact profile used by realtime and offline analysis."""

    template: ExerciseTemplate
    feature_sequence: list[FeatureFrame]
    signal_sequence: list[float]
    stats: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_feature_sequence(
        cls,
        template: ExerciseTemplate,
        feature_sequence: Iterable[FeatureFrame],
    ) -> "TemplateProfile":
        features = list(feature_sequence)
        signals = [f.signal for f in features]
        if signals:
            stats = {
                "signal_min": min(signals),
                "signal_max": max(signals),
                "signal_mean": sum(signals) / len(signals),
                "signal_range": max(signals) - min(signals),
            }
        else:
            stats = {"signal_min": 0.0, "signal_max": 0.0, "signal_mean": 0.0, "signal_range": 0.0}
        return cls(template=template, feature_sequence=features, signal_sequence=signals, stats=stats)


class TemplateLibrary:
    """In-memory template registry with simple filtering and retrieval."""

    def __init__(self) -> None:
        self._profiles: dict[str, TemplateProfile] = {}

    def add_template(self, profile: TemplateProfile) -> None:
        self._profiles[profile.template.template_id] = profile

    def get_template(self, template_id: str) -> TemplateProfile:
        if template_id not in self._profiles:
            raise KeyError(f"Unknown template_id: {template_id}")
        return self._profiles[template_id]

    def list_templates(
        self,
        *,
        view: str | None = None,
        posture: str | None = None,
    ) -> list[TemplateProfile]:
        items = list(self._profiles.values())
        if view is not None:
            items = [item for item in items if item.template.view == view]
        if posture is not None:
            items = [item for item in items if item.template.posture == posture]
        return items

    def has_template(self, template_id: str) -> bool:
        return template_id in self._profiles
