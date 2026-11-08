"""Configuration loading and validation."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CameraConfig:
    name: str
    host: str
    port: int = 80
    # NVR channel index (zero-based); omit for a directly connected camera.
    channel: int | None = None
    listen_port: int = 8000
    username: str = ""
    password: str = ""
    # FOV size in camera position units at full zoom-out.
    # These are used for position-feedback RelativeMove.
    # Adjust per camera if click-to-move overshoots or undershoots.
    fov_pan_units: int = 170
    fov_tilt_units: int = 95
    # Movement speed for position-feedback moves (1-64).
    # Lower = more precise but slower.
    move_speed: int = 15
    # Optional experimental, time-bounded NVR PTZ commands.
    nvr_move_mode: str = "feedback"  # feedback or timed_pulse
    nvr_pulse_ms: int = 120  # initial pulse duration; 50-500 ms
    # Optical magnification at calibrated zoom steps, e.g. {0: 1.0, 20: 2.68}.
    # Used to turn Frigate's drag-to-zoom box into an exact zoom step.
    # Without it, zoom is assumed geometric from 1x to max_zoom_magnification.
    zoom_magnification: dict[int, float] = field(default_factory=dict)
    max_zoom_magnification: float = 4.0


@dataclass
class ProxyConfig:
    cameras: list[CameraConfig] = field(default_factory=list)


def load_config(path: str | Path) -> ProxyConfig:
    """Load proxy configuration from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    cameras = []
    for cam in data.get("cameras", []):
        cameras.append(
            CameraConfig(
                name=cam["name"],
                host=cam["host"],
                port=cam.get("port", 80),
                channel=cam.get("channel"),
                listen_port=cam["listen_port"],
                username=cam.get("username", ""),
                password=cam.get("password", ""),
                fov_pan_units=cam.get("fov_pan_units", 170),
                fov_tilt_units=cam.get("fov_tilt_units", 95),
                move_speed=cam.get("move_speed", 15),
                nvr_move_mode=cam.get("nvr_move_mode", "feedback"),
                nvr_pulse_ms=cam.get("nvr_pulse_ms", 120),
                zoom_magnification={
                    int(k): float(v) for k, v in (cam.get("zoom_magnification") or {}).items()
                },
                max_zoom_magnification=float(cam.get("max_zoom_magnification", 4.0)),
            )
        )

    if not cameras:
        raise ValueError("No cameras configured")

    for camera in cameras:
        if camera.channel is not None and (type(camera.channel) is not int or camera.channel < 0):
            raise ValueError(f"Camera {camera.name}: channel must be a non-negative integer")

    for camera in cameras:
        if camera.nvr_move_mode not in ("feedback", "timed_pulse"):
            raise ValueError(f"Camera {camera.name}: invalid nvr_move_mode")
        if camera.nvr_move_mode == "timed_pulse" and camera.channel is None:
            raise ValueError(f"Camera {camera.name}: timed_pulse requires an NVR channel")
        if type(camera.nvr_pulse_ms) is not int or not 50 <= camera.nvr_pulse_ms <= 500:
            raise ValueError(f"Camera {camera.name}: nvr_pulse_ms must be 50-500")

    # Check for duplicate listen ports
    ports = [c.listen_port for c in cameras]
    if len(ports) != len(set(ports)):
        raise ValueError("Duplicate listen_port values in configuration")

    return ProxyConfig(cameras=cameras)
