"""NVR channel routing regression tests based on observed RLN36 responses."""

import asyncio
from unittest.mock import AsyncMock

from reolink_onvif_proxy.config import CameraConfig
from reolink_onvif_proxy.reolink_api import ReolinkAPI


def run(coro):
    return asyncio.run(coro)


def test_camera_config_channel_default_is_direct_camera():
    camera = CameraConfig(name="direct", host="192.0.2.10")
    assert camera.channel is None


def test_nvr_get_position_uses_nested_channel():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    host = AsyncMock()
    host.send.return_value = [
        {"cmd": "GetPtzCurPos", "code": 0,
         "value": {"PtzCurPos": {"Ppos": 3607, "channel": 8}}}
    ]
    api._api = host
    api._logged_in = True

    pos = run(api.get_position("admin", "password", channel=8))

    assert pos.pan == 3607
    assert pos.tilt == 0
    host.send.assert_awaited_once_with(
        [{"cmd": "GetPtzCurPos", "action": 0,
          "param": {"PtzCurPos": {"channel": 8}}}],
        expected_response_type="json",
    )


def test_nvr_ptz_control_uses_selected_channel():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    host = AsyncMock()
    host.send.return_value = [{"cmd": "PtzCtrl", "code": 0}]
    api._api = host
    api._logged_in = True

    assert run(api.ptz_control("admin", "password", "Left", 16, channel=8))
    host.send.assert_awaited_once_with(
        [{"cmd": "PtzCtrl", "action": 0,
          "param": {"channel": 8, "op": "Left", "speed": 16}}],
        expected_response_type="json",
    )


def test_nvr_ptz_control_reports_api_error():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    host = AsyncMock()
    host.send.return_value = [{"cmd": "PtzCtrl", "code": 1}]
    api._api = host
    api._logged_in = True
    assert not run(api.ptz_control("admin", "password", "Left", 16, channel=8))
