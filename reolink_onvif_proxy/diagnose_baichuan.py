"""Read-only Baichuan PTZ position diagnostic for an NVR camera channel.

Run inside the proxy container:
    python -m reolink_onvif_proxy.diagnose_baichuan --camera fatarolo

Move/tilt the camera using its existing controls, then run again.
No PTZ movement commands are sent by this diagnostic.
"""

import argparse
import asyncio
import json

from .config import load_config
from .reolink_api import ReolinkAPI


async def diagnose(config_path: str, camera_name: str) -> None:
    config = load_config(config_path)
    matches = [cam for cam in config.cameras if cam.name == camera_name]
    if len(matches) != 1:
        raise ValueError(f"Camera {camera_name!r} must match exactly one config entry")

    cam = matches[0]
    if not cam.username or not cam.password:
        raise ValueError("Camera credentials must be specified in config.yml")
    channel = cam.channel if cam.channel is not None else 0
    api = ReolinkAPI(cam.host, cam.port, nvr_mode=cam.channel is not None)
    try:
        host = await api._ensure_connected(cam.username, cam.password)

        # This invokes the Baichuan protocol's command 433 directly. Unlike
        # GetPtzCurPos over HTTP, the Baichuan response may include Tpos.
        # _send_and_parse writes the parsed result to host._ptz_position.
        # A failure here is diagnostic, not proof that tilt is unsupported.
        error = None
        try:
            await host.baichuan._send_and_parse(433, channel)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        values = dict(host._ptz_position.get(channel, {}))
        print(json.dumps({
            "camera": cam.name,
            "channel": channel,
            "source": "Baichuan command 433 (read-only)",
            "pan": values.get("Ppos"),
            "tilt": values.get("Tpos"),
            "fields": sorted(values),
            "error": error,
        }, indent=2))
    finally:
        await api.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read PTZ position via Baichuan")
    parser.add_argument("--config", default="/config.yml")
    parser.add_argument("--camera", required=True)
    args = parser.parse_args()
    asyncio.run(diagnose(args.config, args.camera))


if __name__ == "__main__":
    main()
