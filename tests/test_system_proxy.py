import unittest
from unittest.mock import MagicMock, patch

from app.parsers.system_proxy import bypass_system_proxy


def _completed(returncode=0, stdout=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


class BypassSystemProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_disables_and_restores_manual_proxy(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'manual'\n")
            return _completed()

        with (
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
            patch("app.parsers.system_proxy.shutil.which", return_value="/usr/bin/gsettings"),
            patch("app.parsers.system_proxy.subprocess.run", side_effect=fake_run) as mock_run,
        ):
            async with bypass_system_proxy():
                pass

        set_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][:2] == ["gsettings", "set"]]
        self.assertEqual(set_calls, [])

    async def test_noop_when_gsettings_unavailable(self):
        with (
            patch("app.parsers.system_proxy.shutil.which", return_value=None),
            patch("app.parsers.system_proxy.subprocess.run") as mock_run,
        ):
            async with bypass_system_proxy():
                pass

        mock_run.assert_not_called()

    async def test_restores_proxy_even_on_exception(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ["gsettings", "get", "org.gnome.system.proxy"]:
                return _completed(stdout="'manual'\n")
            return _completed()

        with (
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
