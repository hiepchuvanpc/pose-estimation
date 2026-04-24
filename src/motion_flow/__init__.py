"""Production-oriented OOP skeleton for continuous AI fitness coaching workflow."""

from .models import (
    ExerciseTemplate,
    FeatureFrame,
    PoseFrame,
    RepSegment,
    SessionResult,
    SetResult,
)
from .template_management import TemplateLibrary, TemplateProfile
from .pipeline import PosePipeline
from .features import FeatureExtractor
from .readiness import ReadinessEvaluator
from .tracking import HoldTracker, PhaseDetector, RepCounter, TempoAnalyzer
from .alignment import DTWAligner, MovementScorer, RepSegmenter
from .feedback import FeedbackGenerator
from .workout import SetRecorder, WorkoutSession
from .orchestrator import AIFitnessCoach

__all__ = [
    "AIFitnessCoach",
    "DTWAligner",
    "ExerciseTemplate",
    "FeatureExtractor",
    "FeatureFrame",
    "FeedbackGenerator",
    "HoldTracker",
    "MovementScorer",
    "PhaseDetector",
    "PoseFrame",
    "PosePipeline",
    "ReadinessEvaluator",
    "RepCounter",
    "RepSegment",
    "RepSegmenter",
    "SessionResult",
    "SetRecorder",
    "SetResult",
    "TemplateLibrary",
    "TemplateProfile",
    "TempoAnalyzer",
    "WorkoutSession",
]
