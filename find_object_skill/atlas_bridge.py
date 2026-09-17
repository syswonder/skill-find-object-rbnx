"""Atlas registration and typed MCP entrypoint for the find-object skill."""
from __future__ import annotations

import asyncio
import logging
import time

from robonix_api import ATLAS, Err, Ok, Skill

from find_object_mcp import (
    ReviewLastScan_Request,
    ReviewLastScan_Response,
    ScanForObject_Request,
    ScanForObject_Response,
)

from .controller import SweepController, SweepError

logging.basicConfig(level=logging.INFO, format="[find-object] %(levelname)s %(message)s")
log = logging.getLogger("find_object")

skill = Skill(id="find_object", namespace="robonix/skill/find_object")
controller: SweepController | None = None
config: dict = {}

REQUIRED_INPUTS = {
    "camera": ("robonix/primitive/camera/snapshot", "mcp"),
    "chassis": ("robonix/primitive/chassis/move", "grpc"),
}


def resolve_inputs(deadline_s: float = 45.0) -> dict[str, str]:
    """Resolve camera and chassis exclusively through Atlas contracts."""
    resolved: dict[str, str] = {}
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        for key, (contract_id, transport) in REQUIRED_INPUTS.items():
            if key in resolved:
                continue
            try:
                view = ATLAS.find_unique_capability(
                    contract_id=contract_id, transport=transport
                )
                channel = skill.connect_capability(view, contract_id, transport)
                endpoint = channel.endpoint
                channel.close()
                if endpoint:
                    resolved[key] = endpoint
            except Exception:  # noqa: BLE001
                continue
        if len(resolved) == len(REQUIRED_INPUTS):
            return resolved
        time.sleep(1.0)
    missing = [REQUIRED_INPUTS[k][0] for k in REQUIRED_INPUTS if k not in resolved]
    raise RuntimeError(f"missing Atlas dependencies: {missing}")


@skill.mcp("robonix/skill/find_object/scan")
async def scan(req: ScanForObject_Request) -> ScanForObject_Response:
    """Return an annotated contact sheet without blocking FastMCP's event loop.

    Side effects: the worker thread performs the complete capture/rotate sequence.
    Camera MCP calls may create their own event loops safely inside that thread.
    """
    if controller is None:
        raise RuntimeError("find-object controller is not active")
    try:
        image_base64, detail = await asyncio.to_thread(
            controller.scan, req.target.strip()
        )
    except SweepError as exc:
        raise RuntimeError(f"360-degree scan failed: {exc}") from exc
    return ScanForObject_Response(
        image_base64=image_base64,
        format="jpeg",
        detail=detail,
    )


@skill.mcp("robonix/skill/find_object/review_last_scan")
async def review_last_scan(req: ReviewLastScan_Request) -> ReviewLastScan_Response:
    """Reattach the latest scan for a VLM follow-up without moving the robot."""
    if controller is None:
        raise RuntimeError("find-object controller is not active")
    try:
        image_base64, detail = controller.review_latest(req.question.strip())
    except SweepError as exc:
        raise RuntimeError(f"latest scan is unavailable: {exc}") from exc
    return ReviewLastScan_Response(
        image_base64=image_base64,
        format="jpeg",
        detail=detail,
    )


@skill.on_init
def init(cfg: dict):
    """Store lightweight configuration; defer dependency connections until activation."""
    global config
    config = dict(cfg or {})
    step_deg = float(config.get("step_deg", 45.0))
    if not abs(step_deg * 8.0 - 360.0) < 1e-6:
        return Err("step_deg must be 45 for the fixed eight-frame sweep")
    if float(config.get("scan_memory_ttl_s", 900.0)) <= 0:
        return Err("scan_memory_ttl_s must be greater than zero")
    if not isinstance(config.get("save_images", False), bool):
        return Err("save_images must be a boolean")
    if config.get("save_images", False) and not str(
        config.get("image_output_dir", "")
    ).strip():
        return Err("image_output_dir is required when save_images is true")
    return Ok()


@skill.on_activate
def activate():
    """Resolve dependencies and allocate the controller; remain idempotent."""
    global controller
    if controller is not None:
        return Ok()
    try:
        inputs = resolve_inputs()
        controller = SweepController(
            camera_endpoint=inputs["camera"],
            chassis_endpoint=inputs["chassis"],
            step_deg=float(config.get("step_deg", 45.0)),
            settle_s=float(config.get("settle_s", 0.6)),
            scan_memory_ttl_s=float(config.get("scan_memory_ttl_s", 900.0)),
            save_images=config.get("save_images", False),
            image_output_dir=str(config.get("image_output_dir", "")),
        )
    except Exception as exc:  # noqa: BLE001
        return Err(str(exc))
    log.info("activated with Atlas-resolved camera and chassis")
    return Ok()


@skill.on_deactivate
def deactivate():
    """Release the controller after executor eviction."""
    global controller
    controller = None
    return Ok()


def main() -> int:
    """Serve lifecycle and MCP contracts until shutdown."""
    skill.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
