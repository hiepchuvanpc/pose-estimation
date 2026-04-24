from __future__ import annotations

from motion_core.types import Keypoint

from .models import PoseFrame


def to_core_frame(frame: PoseFrame) -> dict[str, Keypoint]:
    width = max(1, int(frame.frame_width or 1))
    height = max(1, int(frame.frame_height or 1))

    out: dict[str, Keypoint] = {}
    for name, xy in frame.keypoints_xy.items():
        if xy is None:
            continue
        x = float(xy[0])
        y = float(xy[1])
        score = float(frame.keypoint_confidence.get(name, 0.0))

        # PoseFrame may hold normalized coords [0,1] in some flows.
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and (frame.frame_width or frame.frame_height):
            x = x * width
            y = y * height

        out[name] = Keypoint(x=x, y=y, score=score)

    left_hip = out.get("left_hip")
    right_hip = out.get("right_hip")
    if left_hip and right_hip and "mid_hip" not in out:
        out["mid_hip"] = Keypoint(
            x=(left_hip.x + right_hip.x) / 2.0,
            y=(left_hip.y + right_hip.y) / 2.0,
            score=min(left_hip.score, right_hip.score),
        )

    left_shoulder = out.get("left_shoulder")
    right_shoulder = out.get("right_shoulder")
    if left_shoulder and right_shoulder and "neck" not in out:
        out["neck"] = Keypoint(
            x=(left_shoulder.x + right_shoulder.x) / 2.0,
            y=(left_shoulder.y + right_shoulder.y) / 2.0,
            score=min(left_shoulder.score, right_shoulder.score),
        )

    return out
