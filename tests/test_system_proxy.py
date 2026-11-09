import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app.parsers.system_proxy as system_proxy
from app.parsers.system_proxy import bypass_system_proxy


def _completed(returncode=0, stdout=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


class BypassSystemProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._state_patch = patch.object(system_proxy, "_STATE_PATH", root / "proxy-state.json")
        self._lock_patch = patch.object(system_proxy, "_LOCK_PATH", root / "proxy.lock")
        self._state_patch.start()
        self._lock_patch.start()
        self.addCleanup(self._lock_patch.stop)
        self.addCleanup(self._state_patch.stop)
        self.addCleanup(self._tmp.cleanup)

    async def test_disabled_by_default_does_not_touch_desktop_proxy(self):
        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "0"}),
            patch("app.parsers.system_proxy.shutil.which") as which,
            patch("app.parsers.system_proxy.subprocess.run") as mock_run,
        ):
            async with bypass_system_proxy():
                pass

        which.assert_not_called()
        mock_run.assert_not_called()

    async def test_disables_and_restores_manual_proxy_when_opted_in(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'manual'\n")
            return _completed()

        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "1"}),
            patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
            patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run),
        ):
            async with bypass_system_proxy():
                pass

        set_calls = [c for c in calls if c[:2] == ["gsettings", "set"]]
        self.assertEqual(set_calls[0][-1], "none")
        self.assertEqual(set_calls[-1][-1], "manual")

    async def test_noop_when_proxy_already_none(self):
        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'none'\n")
            return _completed()

        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "1"}),
            patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
            patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run) as mock_run,
        ):
            async with bypass_system_proxy():
                pass

        set_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][:2] == ["gsettings", "set"]]
        self.assertEqual(set_calls, [])

    async def test_noop_when_gsettings_unavailable(self):
        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "1"}),
            patch("app.parsers.system_proxy.shutil.which", return_value=None),
            patch("app.parsers.system_proxy.subprocess.run") as mock_run,
        ):
            async with bypass_system_proxy():
                pass

        mock_run.assert_not_called()

    async def test_does_not_enter_context_when_disabling_proxy_fails(self):
        entered = False

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'manual'\n")
            return _completed(returncode=1)

        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "1"}),
            patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
            patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run),
            self.assertRaisesRegex(RuntimeError, "Не удалось отключить системный прокси"),
        ):
            async with bypass_system_proxy():
                entered = True

        self.assertFalse(entered)

    async def test_logs_error_when_proxy_restore_fails(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'manual'\n")
            if cmd[-1] == "manual":
                return _completed(returncode=1)
            return _completed()

        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "1"}),
            patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
            patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run),
            patch("app.parsers.system_proxy.logger.error") as log_error,
        ):
            async with bypass_system_proxy():
                pass

        log_error.assert_called_once()
        self.assertTrue(system_proxy._STATE_PATH.exists())
        self.assertEqual([c[-1] for c in calls if c[:2] == ["gsettings", "set"]], ["none", "manual"])

    async def test_recovers_proxy_left_disabled_by_previous_crash(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "proxy-state.json"
            lock_path = Path(tmp) / "proxy.lock"
            state_path.write_text(json.dumps({"original_mode": "manual"}), encoding="utf-8")
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                    return _completed(stdout="'none'\n")
                return _completed()

            with (
                patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "1"}),
                patch("app.parsers.system_proxy._STATE_PATH", state_path),
                patch("app.parsers.system_proxy._LOCK_PATH", lock_path),
                patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
                patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run),
            ):
                async with bypass_system_proxy():
                    pass

            self.assertFalse(state_path.exists())
            set_modes = [cmd[-1] for cmd in calls if cmd[:2] == ["gsettings", "set"]]
            self.assertEqual(set_modes, ["manual"])

    async def test_recovers_stale_proxy_even_when_bypass_is_disabled(self):
        import json

        state_path = system_proxy._STATE_PATH
        state_path.write_text(json.dumps({"original_mode": "manual"}), encoding="utf-8")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'none'\n")
            return _completed()

        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "0"}),
            patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
            patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run),
        ):
            async with bypass_system_proxy():
                pass

        self.assertFalse(state_path.exists())
        set_modes = [cmd[-1] for cmd in calls if cmd[:2] == ["gsettings", "set"]]
        self.assertEqual(set_modes, ["manual"])

    async def test_restores_proxy_even_on_exception(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'manual'\n")
            return _completed()

        with (
            patch.dict("os.environ", {"MARKETMIND_BYPASS_SYSTEM_PROXY": "1"}),
            patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
            patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run),
            self.assertRaises(ValueError),
        ):
            async with bypass_system_proxy():
                raise ValueError("boom")

        set_calls = [c for c in calls if c[:2] == ["gsettings", "set"]]
        self.assertEqual(set_calls[-1][-1], "manual")


if __name__ == "__main__":
    unittest.main()
