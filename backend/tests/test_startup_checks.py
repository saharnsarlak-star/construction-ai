"""Startup configuration warnings."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.startup_checks import run_startup_checks


class StartupChecksTests(unittest.TestCase):
    @patch("app.startup_checks.settings")
    def test_warns_on_sqlite_and_default_password(self, mock_settings) -> None:
        mock_settings.database_url = "sqlite+aiosqlite:///./local.db"
        mock_settings.admin_password = "Admin123!"
        mock_settings.user_password = "User123!"
        mock_settings.admin_api_token = "dev-admin-token"
        mock_settings.max_upload_mb = 200
        mock_settings.new_rule_engine_enabled = False
        mock_settings.ai_rule_engine_enabled = False
        mock_settings.knowledge_graph_enabled = False
        mock_settings.ti_semantic_standards_enabled = False
        warnings = run_startup_checks()
        self.assertTrue(any("SQLite" in w for w in warnings))
        self.assertTrue(any("ADMIN_PASSWORD" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
