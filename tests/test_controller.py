from __future__ import annotations

import base64
from io import BytesIO
import unittest

from PIL import Image

from find_object_skill.controller import (
    _signed_relative_angle,
    RotationError,
    SweepController,
    SweepError,
    make_contact_sheet,
)


def jpeg(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 60), color).save(output, format="JPEG")
    return output.getvalue()


class SweepControllerTest(unittest.TestCase):
    def test_capture_precedes_each_rotation_and_eighth_rotation_returns_home(self) -> None:
        events: list[str] = []

        def capture() -> bytes:
            events.append("capture")
            return jpeg((20, 40, 60))

        def rotate(degrees: float) -> float:
            events.append(f"rotate:{degrees}")
            return degrees

        controller = SweepController(
            camera_endpoint="unused",
            chassis_endpoint="unused",
            settle_s=0.0,
            capture=capture,
            rotate=rotate,
        )
        encoded, detail = controller.scan("water bottle")

        self.assertEqual(events, ["capture", "rotate:45.0"] * 8)
        self.assertTrue(base64.b64decode(encoded).startswith(b"\xff\xd8"))
        self.assertIn("360.0 deg", detail)

    def test_failure_attempts_inverse_heading_recovery(self) -> None:
        rotations: list[float] = []
        captures = 0

        def capture() -> bytes:
            nonlocal captures
            captures += 1
            if captures == 3:
                raise RuntimeError("camera lost")
            return jpeg((0, 0, 0))

        def rotate(degrees: float) -> float:
            rotations.append(degrees)
            return degrees

        controller = SweepController(
            camera_endpoint="unused",
            chassis_endpoint="unused",
            settle_s=0.0,
            capture=capture,
            rotate=rotate,
        )
        with self.assertRaises(SweepError):
            controller.scan("bottle")
        self.assertEqual(rotations, [45.0, 45.0, -90.0])

    def test_contact_sheet_requires_exactly_eight_frames(self) -> None:
        with self.assertRaises(ValueError):
            make_contact_sheet([Image.new("RGB", (10, 10))] * 7, "bottle")

    def test_partial_failed_rotation_is_included_in_recovery(self) -> None:
        rotations: list[float] = []

        def rotate(degrees: float) -> float:
            rotations.append(degrees)
            if len(rotations) == 2:
                raise RotationError("odometry stale", 12.0)
            return degrees

        controller = SweepController(
            camera_endpoint="unused",
            chassis_endpoint="unused",
            settle_s=0.0,
            capture=lambda: jpeg((0, 0, 0)),
            rotate=rotate,
        )
        with self.assertRaises(SweepError):
            controller.scan("bottle")
        self.assertEqual(rotations, [45.0, 45.0, -57.0])

    def test_tile_angles_are_robot_relative_and_signed(self) -> None:
        self.assertEqual(
            [_signed_relative_angle(index * 45.0) for index in range(8)],
            [0.0, 45.0, 90.0, 135.0, 180.0, -135.0, -90.0, -45.0],
        )

    def test_each_rotation_compensates_previous_closed_loop_error(self) -> None:
        commands: list[float] = []

        def rotate(degrees: float) -> float:
            commands.append(degrees)
            return degrees - 2.0

        controller = SweepController(
            camera_endpoint="unused",
            chassis_endpoint="unused",
            settle_s=0.0,
            capture=lambda: jpeg((0, 0, 0)),
            rotate=rotate,
        )
        _, detail = controller.scan("bottle")

        self.assertEqual(commands, [45.0] + [47.0] * 7)
        self.assertIn("358.0 deg", detail)


if __name__ == "__main__":
    unittest.main()
