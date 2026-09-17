"""Deterministic capture/rotate sequence and annotated contact-sheet output."""
from __future__ import annotations

import asyncio
import base64
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable

import grpc
from PIL import Image, ImageDraw, ImageFont, ImageOps

import chassis_pb2
import robonix_contracts_pb2_grpc

log = logging.getLogger("find_object")

RELATIVE_DIRECTIONS = (
    "front",
    "front-left",
    "left",
    "rear-left",
    "rear",
    "rear-right",
    "right",
    "front-right",
)


class SweepError(RuntimeError):
    """Report a failed sweep after motion recovery has been attempted."""


class RotationError(SweepError):
    """Preserve partial measured motion so failure recovery can undo it."""

    def __init__(self, message: str, actual_deg: float) -> None:
        super().__init__(message)
        self.actual_deg = actual_deg


class NoRecentScanError(SweepError):
    """Report that no sufficiently recent sweep is available for review."""


class SweepController:
    """Capture eight headings and command closed-loop chassis rotations."""

    def __init__(
        self,
        *,
        camera_endpoint: str,
        chassis_endpoint: str,
        step_deg: float = 45.0,
        settle_s: float = 0.6,
        scan_memory_ttl_s: float = 900.0,
        save_images: bool = False,
        image_output_dir: str = "",
        capture: Callable[[], bytes] | None = None,
        rotate: Callable[[float], float] | None = None,
    ) -> None:
        """Store resolved endpoints and injectable I/O functions for testing."""
        if not math.isclose(step_deg * 8.0, 360.0, abs_tol=1e-6):
            raise ValueError("step_deg must divide one eight-frame 360-degree sweep")
        self.camera_endpoint = camera_endpoint
        self.chassis_endpoint = _grpc_target(chassis_endpoint)
        self.step_deg = step_deg
        self.settle_s = max(0.0, settle_s)
        if scan_memory_ttl_s <= 0:
            raise ValueError("scan_memory_ttl_s must be greater than zero")
        self.scan_memory_ttl_s = scan_memory_ttl_s
        self.save_images = save_images
        self.image_output_dir: Path | None = None
        if save_images:
            if not image_output_dir.strip():
                raise ValueError("image_output_dir is required when save_images is true")
            output_dir = Path(image_output_dir).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            if not output_dir.is_dir():
                raise ValueError(f"image_output_dir is not a directory: {output_dir}")
            self.image_output_dir = output_dir.resolve()
        self._capture_override = capture
        self._rotate_override = rotate
        self._run_lock = threading.Lock()
        self._latest_scan: tuple[bytes, str, float] | None = None

    def scan(self, target: str) -> tuple[str, str]:
        """Capture before each rotation, finish at the initial heading, and build JPEG output.

        Side effects: issues eight bounded chassis commands. If capture or motion fails,
        attempt a closed-loop inverse rotation using measured completed angles.
        """
        if not self._run_lock.acquire(blocking=False):
            raise SweepError("another 360-degree sweep is already running")
        frames: list[Image.Image] = []
        accumulated_deg = 0.0
        try:
            for index in range(8):
                frames.append(self._capture_image())
                target_cumulative_deg = (index + 1) * self.step_deg
                command_deg = target_cumulative_deg - accumulated_deg
                try:
                    actual = self._rotate(command_deg)
                except RotationError as exc:
                    accumulated_deg += exc.actual_deg
                    raise
                accumulated_deg += actual
                log.info(
                    "sweep step %d/8: target=%.1f command=%.1f actual=%.1f cumulative=%.1f error=%+.1f deg",
                    index + 1,
                    target_cumulative_deg,
                    command_deg,
                    actual,
                    accumulated_deg,
                    accumulated_deg - target_cumulative_deg,
                )
                if index != 7 and self.settle_s:
                    time.sleep(self.settle_s)
            mosaic = make_contact_sheet(frames, target, self.step_deg)
            output = BytesIO()
            mosaic.save(output, format="JPEG", quality=88, optimize=True)
            jpeg = output.getvalue()
            captured_at = time.time()
            detail = (
                f"captured 8 headings for target {target!r}; "
                f"measured cumulative rotation={accumulated_deg:.1f} deg"
            )
            if self.image_output_dir is not None:
                saved_path = _save_contact_sheet(jpeg, self.image_output_dir, target)
                detail += f"; saved contact sheet to {saved_path}"
            self._latest_scan = (jpeg, target, captured_at)
            return base64.b64encode(jpeg).decode("ascii"), detail
        except Exception as exc:
            self._restore_heading(accumulated_deg)
            raise SweepError(str(exc)) from exc
        finally:
            self._run_lock.release()

    def review_latest(self, question: str) -> tuple[str, str]:
        """Return the latest contact sheet so Pilot can answer a follow-up question.

        The image is process-local short-term visual memory. It expires to prevent a
        stale observation from being presented as the robot's current surroundings.
        """
        latest = self._latest_scan
        if latest is None:
            raise NoRecentScanError("no completed scan is available; run scan first")
        jpeg, target, captured_at = latest
        age_s = max(0.0, time.time() - captured_at)
        if age_s > self.scan_memory_ttl_s:
            raise NoRecentScanError(
                f"latest scan is {age_s:.0f}s old and has expired; run scan again"
            )
        detail = (
            f"reviewing latest scan captured {age_s:.0f}s ago for target {target!r}; "
            f"question={question!r}; answer only from visible evidence in this image"
        )
        return base64.b64encode(jpeg).decode("ascii"), detail

    def _capture_image(self) -> Image.Image:
        """Fetch one JPEG snapshot through the atlas-resolved camera MCP endpoint."""
        jpeg = self._capture_override() if self._capture_override else self._capture_mcp()
        try:
            image = Image.open(BytesIO(jpeg))
            image.load()
            return image.convert("RGB")
        except Exception as exc:
            raise SweepError(f"camera returned an invalid JPEG: {exc}") from exc

    def _capture_mcp(self) -> bytes:
        """Call the camera snapshot MCP tool once and decode its base64 payload."""
        from fastmcp import Client

        async def call() -> dict[str, Any]:
            async with Client(self.camera_endpoint) as client:
                result = await client.call_tool("snapshot", {})
                if not result.content:
                    return {}
                return json.loads(result.content[0].text)

        response = asyncio.run(call())
        encoding = str(response.get("encoding", "")).lower()
        payload = response.get("data", "")
        if encoding != "jpeg" or not payload:
            raise SweepError(f"camera snapshot failed (encoding={encoding or 'missing'})")
        return base64.b64decode(payload, validate=True)

    def _rotate(self, degrees: float) -> float:
        """Execute one odometry-closed-loop chassis rotation and return measured angle."""
        if self._rotate_override:
            return float(self._rotate_override(degrees))
        channel = grpc.insecure_channel(self.chassis_endpoint)
        try:
            stub = robonix_contracts_pb2_grpc.RobonixPrimitiveChassisMoveStub(channel)
            command = chassis_pb2.MoveCommand(rotate_deg=float(degrees))
            response = stub.ExecuteMoveCommand(
                chassis_pb2.ExecuteMoveCommand_Request(command=command), timeout=20.0
            )
            status = json.loads(response.status.data or "{}")
        finally:
            channel.close()
        actual = float(status.get("actual_rotate_deg", 0.0))
        if status.get("status") != "done":
            raise RotationError(
                f"chassis rotation failed after {actual:.1f} deg: "
                f"{status.get('error', 'unknown error')}",
                actual,
            )
        return actual

    def _restore_heading(self, accumulated_deg: float) -> None:
        """Best-effort return to the initial heading after an interrupted sweep."""
        residual = math.remainder(accumulated_deg, 360.0)
        if abs(residual) < 3.0:
            return
        try:
            self._rotate(-residual)
            log.warning("recovered initial heading after sweep failure (%.1f deg)", residual)
        except Exception as exc:  # noqa: BLE001
            log.error("failed to recover initial heading: %s", exc)


def _grpc_target(endpoint: str) -> str:
    """Normalize an atlas gRPC endpoint for grpcio."""
    return endpoint.removeprefix("http://").removeprefix("https://").replace(
        "localhost", "127.0.0.1"
    )


def _save_contact_sheet(jpeg: bytes, output_dir: Path, target: str) -> Path:
    """Atomically save one contact sheet under a timestamped safe filename."""
    safe_target = re.sub(r"[^A-Za-z0-9._-]+", "-", target.strip()).strip("-._")
    safe_target = re.sub(r"\.{2,}", "-", safe_target)
    safe_target = safe_target[:64] or "scan"
    timestamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    fd, temporary_name = tempfile.mkstemp(prefix=".scan-", suffix=".tmp", dir=output_dir)
    nanoseconds = time.time_ns() % 1_000_000_000
    destination = output_dir / f"{timestamp}-{nanoseconds:09d}_{safe_target}.jpg"
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(jpeg)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def make_contact_sheet(
    frames: list[Image.Image], target: str, step_deg: float = 45.0
) -> Image.Image:
    """Create a 4x2 JPEG-friendly contact sheet with index and heading labels."""
    if len(frames) != 8:
        raise ValueError("exactly eight frames are required")
    tile_size = (480, 360)
    header_h = 48
    sheet = Image.new("RGB", (tile_size[0] * 4, (tile_size[1] + 34) * 2 + header_h), "#111")
    draw = ImageDraw.Draw(sheet)
    font = _font(22)
    small = _font(18)
    draw.text(
        (14, 12),
        f"360 scan | target: {target or 'unspecified'} | angles relative to robot front",
        fill="white",
        font=font,
    )
    for index, frame in enumerate(frames):
        tile = ImageOps.fit(frame.convert("RGB"), tile_size, method=Image.Resampling.LANCZOS)
        x = (index % 4) * tile_size[0]
        y = header_h + (index // 4) * (tile_size[1] + 34)
        sheet.paste(tile, (x, y))
        signed_center = _signed_relative_angle(index * step_deg)
        low = signed_center - step_deg / 2.0
        high = signed_center + step_deg / 2.0
        label = (
            f"#{index + 1} {RELATIVE_DIRECTIONS[index]} "
            f"{signed_center:+.0f} deg [{low:+.1f}, {high:+.1f}]"
        )
        draw.rectangle((x, y + tile_size[1], x + tile_size[0], y + tile_size[1] + 34), fill="#111")
        draw.text((x + 10, y + tile_size[1] + 6), label, fill="white", font=small)
    return sheet


def _signed_relative_angle(angle_deg: float) -> float:
    """Map counter-clockwise sweep headings to signed robot-relative angles."""
    wrapped = (angle_deg + 180.0) % 360.0 - 180.0
    return 180.0 if math.isclose(wrapped, -180.0) else wrapped


def _font(size: int) -> ImageFont.ImageFont:
    """Use a common Unicode font when available and otherwise use PIL's default."""
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()
