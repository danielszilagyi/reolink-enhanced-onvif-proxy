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


def test_nvr_skips_upward_tilt_at_mechanical_limit():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    api._axis_position = AsyncMock(return_value=0)
    api._move_axis = AsyncMock()

    assert run(api.relative_move_feedback(
        "admin", "password", pan=0.0, tilt=0.611,
        pan_units=340, tilt_units=190, move_speed=15, channel=8,
    ))
    api._axis_position.assert_awaited_once()
    api._move_axis.assert_not_awaited()


def test_nvr_tilt_down_allowed_from_upper_limit():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    api._axis_position = AsyncMock(return_value=0)
    api._move_axis = AsyncMock()

    assert run(api.relative_move_feedback(
        "admin", "password", pan=0.0, tilt=-0.611,
        pan_units=340, tilt_units=190, move_speed=15, channel=8,
    ))
    assert api._move_axis.await_count == 1
    assert api._move_axis.await_args.args[3][0] == "Down"

def test_nvr_lead_is_capped_to_prevent_premature_stop():
    from unittest.mock import patch

    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    api._lead["pan"] = 95.0
    # 100 -> 110 -> 180: a 100-unit request must not stop at 110 merely
    # because an earlier movement had an unusually large learned lead.
    positions = iter([100, 110, 180, 180, 180, 180, 180])
    api._axis_position = AsyncMock(side_effect=lambda *args: next(positions, 180))
    api.ptz_control = AsyncMock(return_value=True)

    async def instant_sleep(_seconds):
        return None

    with patch("reolink_onvif_proxy.reolink_api.asyncio.sleep", new=instant_sleep):
        run(api._move_axis(
            "admin", "password", "pan", ("Right", "Left"),
            distance=100.0, tolerance=2.0, move_speed=15, channel=8,
        ))

    assert api._axis_position.await_count >= 4
    commands = [call.args[2] for call in api.ptz_control.await_args_list]
    assert commands == ["Right", "Stop"]


def test_queued_nvr_relative_moves_both_complete_in_order():
    from reolink_onvif_proxy.onvif_server import ONVIFServer

    async def scenario():
        api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
        server = ONVIFServer(CameraConfig(name="nvr", host="192.0.2.20"), api)
        began = asyncio.Event()
        release = asyncio.Event()
        completed = []

        async def first():
            began.set()
            await release.wait()
            completed.append("first")

        async def second():
            completed.append("second")

        server._queue_action(lambda: first())
        await began.wait()
        server._queue_action(lambda: second())
        assert not completed
        assert server.state.busy
        release.set()
        await server._action_task
        await asyncio.sleep(0)
        assert completed == ["first", "second"]
        assert not server.state.busy

    run(scenario())


def test_stop_cancels_active_and_queued_nvr_moves():
    from reolink_onvif_proxy.onvif_server import ONVIFServer

    async def scenario():
        api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
        server = ONVIFServer(CameraConfig(name="nvr", host="192.0.2.20"), api)
        began = asyncio.Event()
        completed = []

        async def first():
            began.set()
            await asyncio.Event().wait()

        async def second():
            completed.append("unexpected")

        server._queue_action(lambda: first())
        await began.wait()
        server._queue_action(lambda: second())
        tasks = tuple(server._action_tasks)
        server._cancel_action()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert not completed
        assert not server.state.busy

    run(scenario())


def test_timed_nvr_pulse_stops_before_sampling_position():
    from unittest.mock import patch

    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    operations = []
    readings = iter([2500] + [2520] * 12)

    async def position(*_args):
        operations.append("read")
        return next(readings)

    async def control(_user, _password, op, speed=0, channel=0):
        operations.append(op)
        return True

    async def quick_sleep(_seconds):
        return None

    api._axis_position = AsyncMock(side_effect=position)
    api.ptz_control = AsyncMock(side_effect=control)
    with patch("reolink_onvif_proxy.reolink_api.asyncio.sleep", new=quick_sleep):
        run(api._move_axis_timed(
            "admin", "password", "pan", "Right",
            distance=40, move_speed=3, channel=8, pulse_ms=120,
        ))

    assert operations[:3] == ["read", "Right", "Stop"]
    assert operations.count("read") == 13


def test_timed_pulse_is_opt_in_and_routes_relative_move():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    api._move_axis_timed = AsyncMock()
    api._move_axis = AsyncMock()
    result = run(api.relative_move_feedback(
        "admin", "password", pan=0.5, tilt=0.0,
        pan_units=390, tilt_units=260, move_speed=3, channel=8,
        nvr_pulse_ms=120,
    ))
    assert result
    api._move_axis_timed.assert_awaited_once()
    api._move_axis.assert_not_awaited()


def test_timed_pulse_invalid_config_rejected(tmp_path):
    import pytest
    from reolink_onvif_proxy.config import load_config

    cfg = tmp_path / "config.yml"
    cfg.write_text("""cameras:
  - name: test
    host: 192.0.2.20
    channel: 8
    listen_port: 8001
    nvr_move_mode: timed_pulse
    nvr_pulse_ms: 10
""")
    with pytest.raises(ValueError, match="nvr_pulse_ms"):
        load_config(cfg)


def test_nvr_invalid_zoom_retains_last_valid_position():
    api = ReolinkAPI("192.0.2.20", 80, nvr_mode=True)
    host = AsyncMock()
    host.zoom_range.return_value = {
        "zoom": {"min": 0, "max": 27, "pos": -1},
        "focus": {"min": 0, "max": 255, "pos": 0},
    }
    host.send.return_value = [{
        "code": 0,
        "value": {"ZoomFocus": {"zoom": {"pos": 11}, "focus": {"pos": 0}}},
    }]
    api._api = host
    api._logged_in = True

    first = run(api.get_zoom_focus("admin", "password", channel=8))
    assert first.zoom_pos == 11
    host.get_states.assert_not_awaited()

    host.send.return_value = [{
        "code": 0,
        "value": {"ZoomFocus": {"zoom": {"pos": -1}, "focus": {"pos": 0}}},
    }]
    second = run(api.get_zoom_focus("admin", "password", channel=8))
    assert second.zoom_pos == 11
    assert api._last_valid_zoom[8] == 11
