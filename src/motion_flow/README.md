# motion_flow (OOP AI Fitness Coaching Skeleton)

This package provides a production-oriented architecture skeleton for a continuous flow:

1. template ingestion
2. realtime workout session execution
3. per-set post analysis with DTW

## Folder Structure

- `motion_flow/models.py`: shared dataclasses
- `motion_flow/template_management.py`: `TemplateLibrary`, `TemplateProfile`
- `motion_flow/pipeline.py`: `PosePipeline` (normalize/smooth/missing keypoints)
- `motion_flow/features.py`: `FeatureExtractor` (angles, velocity, signal)
- `motion_flow/readiness.py`: `ReadinessEvaluator`
- `motion_flow/tracking.py`: `PhaseDetector`, `RepCounter`, `HoldTracker`, `TempoAnalyzer`
- `motion_flow/workout.py`: `WorkoutSession`, `SetRecorder`
- `motion_flow/alignment.py`: `DTWAligner`, `RepSegmenter`, `MovementScorer`
- `motion_flow/feedback.py`: `FeedbackGenerator`
- `motion_flow/orchestrator.py`: `AIFitnessCoach` end-to-end coordinator
- `motion_flow/example_workflow.py`: runnable demo workflow

## Design Notes

- Same pipeline object is reused for template, realtime, and post-analysis.
- No raw-coordinate scoring; all scoring is feature-based.
- DTW is applied after rep segmentation.
- Readiness gate blocks tracking and scoring when setup quality is poor.

## Run Demo

```bash
python -m motion_flow.example_workflow
```
