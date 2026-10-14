"""Windows test-process adapter for standard unittest.

Collect only unreachable objects before TemporaryDirectory.cleanup. SQLite
connections still held by live objects will remain open and fail tests; errors
are never suppressed.
"""
import gc
import os
import tempfile
import unittest

if os.name == "nt":
    _cleanup = tempfile.TemporaryDirectory.cleanup

    def _before_cleanup(self):
        try:
            return _cleanup(self)
        except PermissionError:
            # Windows can retain handles for unreachable sqlite3 cursors.
            # Reclaim them only on actual deletion failure; never ignore locks
            # held by live objects, so real resource leaks still fail tests.
            gc.collect()
            return _cleanup(self)

    tempfile.TemporaryDirectory.cleanup = _before_cleanup

if __name__ == "__main__":
    unittest.main(module=None)
