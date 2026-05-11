from __future__ import annotations

from .models import SessionResult, SetResult


class FeedbackGenerator:
    """Transforms structured errors and scores into actionable coaching feedback."""

    def per_set_feedback(self, result: SetResult) -> list[str]:
        lines: list[str] = []
        if not result.rep_scores:
            return ["No detectable reps in this set. Reposition and retry."]

        avg = sum(result.rep_scores) / len(result.rep_scores)
        lines.append(f"Set {result.set_index}: average score {avg:.1f}/100.")

        worst_idx = min(range(len(result.rep_scores)), key=lambda i: result.rep_scores[i])
        lines.append(f"Rep {worst_idx + 1} needs most correction.")

        if result.joint_errors:
            top_joint = max(result.joint_errors[0], key=result.joint_errors[0].get)
            lines.append(f"Focus on {top_joint} control for better alignment.")
        return lines

    def session_summary(self, result: SessionResult) -> list[str]:
        if not result.set_results:
            return ["Session finished with no analyzed sets."]

        all_scores = [s for item in result.set_results for s in item.rep_scores]
        if not all_scores:
            return ["Session had no valid reps for scoring."]

        avg = sum(all_scores) / len(all_scores)
        return [
            f"Session average score: {avg:.1f}/100.",
            "Keep camera framing stable for more consistent coaching feedback.",
        ]
