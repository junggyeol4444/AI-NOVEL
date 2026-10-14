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
        gc.collect()
        return _cleanup(self)

    tempfile.TemporaryDirectory.cleanup = _before_cleanup

if __name__ == "__main__":
    unittest.main(module=None)
