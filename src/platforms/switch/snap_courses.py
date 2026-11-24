"""The New Pokémon Snap courses exposed by RAE's scene preview."""
from __future__ import annotations

from dataclasses import dataclass

SNAP_COURSE_MAGIC = "SNAP"


@dataclass(frozen=True, slots=True)
class SnapCourse:
    code: str
    asset_id: str
    label: str
    backdrop: str
    start: tuple[float, float, float]
    target: tuple[float, float, float]
    background: str
    fog: tuple[float, float]
    texture_limit: int | None = None

    @property
    def pack_path(self) -> str:
        return f"/nx/Pack/LevelComposite/master/LC_{self.code}.drp"

    @property
    def scene_name(self) -> str:
        return f"LV_ENV_{self.code}"

    @property
    def model_prefix(self) -> str:
        return f"SM_ENV_{self.code.rsplit('_', 1)[0]}_"


ILLUMINA_SPOT = SnapCourse(
    "004_3_C", "switch_snap_illumina_spot", "Lental Seafloor — Illumina Spot",
    "SM_ENV_004_3_Sky", (0, 33, 225), (0, -8, 15), "#153f72", (35, 335),
)
UNDERSEA = SnapCourse(
    "004_1_A", "switch_snap_undersea", "Lental Seafloor — Undersea",
    "SM_ENV_004_1_Ground", (-37, -4, 56), (-26, -8, 10), "#154466", (14, 130), 1024,
)

SNAP_COURSES = {course.pack_path: course for course in (ILLUMINA_SPOT, UNDERSEA)}
