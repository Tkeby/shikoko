"""Unit tests for pysquirrel.introspect.connection — version gate logic.

These tests verify the version-check logic without requiring a live Postgres.
The integration test (test_connection.py in integration/) exercises the full
pool lifecycle against a real database.
"""

from __future__ import annotations

from pysquirrel.introspect.connection import _MIN_SERVER_VERSION


class TestConstants:
    def test_min_server_version_is_16(self) -> None:
        assert _MIN_SERVER_VERSION == 160000
