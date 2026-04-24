from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Keypoint:
    """2D keypoint with confidence score."""
    x: float
    y: float
    score: float


@dataclass(frozen=True)
class Keypoint3D:
    """3D keypoint with world coordinates and visibility."""
    x: float  # normalized image x [0,1]
    y: float  # normalized image y [0,1]
    z: float  # relative depth
    visibility: float  # detection confidence
    # World coordinates (metric, hip-centered)
    wx: float = 0.0
    wy: float = 0.0
    wz: float = 0.0
    world_visibility: float = 0.0


Frame = Dict[str, Keypoint]
Frame3D = Dict[str, Keypoint3D]


def keypoint3d_from_mediapipe(lm, world_lm=None) -> Keypoint3D:
    """Convert MediaPipe landmark to Keypoint3D."""
    vis = float(getattr(lm, "visibility", 0.0))
    if world_lm is not None:
        return Keypoint3D(
            x=float(lm.x),
            y=float(lm.y),
            z=float(lm.z),
            visibility=vis,
            wx=float(world_lm.x),
            wy=float(world_lm.y),
            wz=float(world_lm.z),
            world_visibility=float(getattr(world_lm, "visibility", getattr(world_lm, "presence", vis))),
        )
    return Keypoint3D(
        x=float(lm.x),
        y=float(lm.y),
        z=float(lm.z),
        visibility=vis,
    )
