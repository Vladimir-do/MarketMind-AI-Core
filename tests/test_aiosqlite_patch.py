import types
import unittest

from app.compat.aiosqlite_patch import (
    _VALIDATED_AIOSQLITE_VERSION,
    _patch_incompatible,
    apply_aiosqlite_future_poll_patch,
)


class PatchIncompatibleErrorTests(unittest.TestCase):
    def test_message_names_both_versions_and_wraps_original_error(self):
        original = AttributeError("'Connection' object has no attribute '_tx'")
        err = _patch_incompatible(original, "9.9.9")
        self.assertIsInstance(err, RuntimeError)
        self.assertIn("incompatible", str(err))
        self.assertIn("9.9.9", str(err))
        self.assertIn(_VALIDATED_AIOSQLITE_VERSION, str(err))
        self.assertIn("_tx", str(err))


class ApplyPatchVersionWarningTests(unittest.TestCase):
    def test_warns_when_installed_version_does_not_match_validated_version(self):
        import aiosqlite
        from aiosqlite.core import Connection

        original_flag = getattr(Connection, "_marketmind_future_poll_patch", False)
        original_version = getattr(aiosqlite, "__version__", None)
        Connection._marketmind_future_poll_patch = False
        aiosqlite.__version__ = "0.0.1-does-not-exist"
        try:
            with self.assertLogs("parser", level="WARNING") as logs:
                apply_aiosqlite_future_poll_patch()
            self.assertTrue(
                any("aiosqlite_patch.py was last verified against" in msg for msg in logs.output),
                f"expected a version-mismatch warning, got: {logs.output}",
            )
        finally:
            aiosqlite.__version__ = original_version
            Connection._marketmind_future_poll_patch = original_flag


class PatchedConnectionAttributeErrorTests(unittest.IsolatedAsyncioTestCase):
    """If aiosqlite's internals ever change shape, the patched methods must
    raise a clear, actionable RuntimeError instead of a bare AttributeError
    deep inside a scraping/DB call."""

    async def asyncSetUp(self):
        from aiosqlite.core import Connection

        # Ensure the real patch is applied (it normally is via app.database's
        # module-level import), so Connection._connect/_execute/close are the
        # patched versions under test.
        apply_aiosqlite_future_poll_patch()
        self.Connection = Connection

    async def test_connect_wraps_missing_internal_attribute(self):
        # A fake "self" that looks nothing like a real aiosqlite Connection --
        # simulates a future aiosqlite release renaming/removing _tx.
        fake_self = types.SimpleNamespace(_connection=None, stop=lambda: None)
        with self.assertRaises(RuntimeError) as ctx:
            await self.Connection._connect(fake_self)
        self.assertIn("incompatible", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, AttributeError)

    async def test_execute_wraps_missing_internal_attribute(self):
        fake_self = types.SimpleNamespace(_connection=object(), _running=True)
        with self.assertRaises(RuntimeError) as ctx:
            await self.Connection._execute(fake_self, lambda: None)
        self.assertIn("incompatible", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, AttributeError)


if __name__ == "__main__":
    unittest.main()
