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


def test_nvr_get_position_uses_baichuan_pan_and_tilt():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    host = AsyncMock()
    host._ptz_position = {8: {"Ppos": 3607, "Tpos": 945}}
    api._api = host
    api._logged_in = True
    api._has_tilt = True

    pos = run(api.get_position("admin", "password", channel=8))

    assert pos.pan == 3607
    assert pos.tilt == 945
    host.baichuan._send_and_parse.assert_awaited_once_with(433, 8)
    host.send.assert_not_awaited()


def test_nvr_does_not_advertise_rejected_set3dpos():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    host = AsyncMock()
    host._ptz_position = {8: {"Ppos": 3607, "Tpos": 89}}
    api._api = host
    api._logged_in = True
    run(api.probe_capabilities("admin", "password", channel=8))
    assert not api.supports_3d_pos
    assert api.has_tilt
    host.baichuan._send_and_parse.assert_awaited_once_with(433, 8)


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


def test_nvr_skips_sub_resolution_tilt_without_motor_command():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    api._move_axis = AsyncMock()

    result = run(api.relative_move_feedback(
        "admin", "password",
        pan=0.0, tilt=0.037,
        pan_units=340, tilt_units=190,
        move_speed=15, channel=8,
    ))

    assert result is True
    api._move_axis.assert_not_awaited()


def test_nvr_retains_normal_sized_relative_move():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    api._move_axis = AsyncMock()

    result = run(api.relative_move_feedback(
        "admin", "password",
        pan=0.5, tilt=0.0,
        pan_units=340, tilt_units=190,
        move_speed=15, channel=8,
    ))

    assert result is True
    assert api._move_axis.await_count == 1
    assert api._move_axis.await_args.args[2] == "pan"
