"""An untouched .env.example (placeholder values) must count as 'not configured', not as a connection error."""
import unittest

from supplyshield.config import get_settings


class PlaceholderSettings(unittest.TestCase):
    def test_env_example_placeholders_are_not_configured(self):
        s = get_settings({"EXASOL_DSN": "<host-or-ip>:<port>", "EXASOL_USER": "<your-exasol-user>",
                          "EXASOL_PASSWORD": "<your-exasol-password>"})
        self.assertFalse(s.configured)
        self.assertEqual(s.missing(), ["EXASOL_DSN", "EXASOL_USER", "EXASOL_PASSWORD"])

    def test_real_looking_values_are_configured(self):
        s = get_settings({"EXASOL_DSN": "db.example.invalid:8563", "EXASOL_USER": "someone", "EXASOL_PASSWORD": "not-a-real-secret"})
        self.assertTrue(s.configured)

    def test_partially_filled(self):
        s = get_settings({"EXASOL_DSN": "db.example.invalid:8563", "EXASOL_USER": "someone", "EXASOL_PASSWORD": "<your-exasol-password>"})
        self.assertEqual(s.missing(), ["EXASOL_PASSWORD"])


if __name__ == "__main__":
    unittest.main()
