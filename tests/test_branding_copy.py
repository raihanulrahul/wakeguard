"""Owner-approved setup copy; preserve spelling, capitalization and punctuation."""
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from wakeguard.app import App
from wakeguard.dashboard import Dashboard


@unittest.skipUnless(os.environ.get("WAKEGUARD_GUI_TESTS") == "1" or os.environ.get("DISPLAY"),
                     "GUI requires Windows desktop or Xvfb")
class BrandingCopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"WAKEGUARD_DATA_DIR": self.tmp.name})
        self.env.start()
        self.root = tk.Tk()
        self.app = None

    def tearDown(self):
        if self.app is not None and not self.app.closing:
            self.app.quit()
        elif self.app is None:
            self.root.destroy()
        self.env.stop()
        self.tmp.cleanup()

    def assert_approved_copy(self):
        self.assertEqual(self.app.view.heading.cget("text"), "Stay Alert")
        self.assertEqual(self.app.view.subtitle.cget("text"), "Look awake, keep your KPI")

    def test_initial_widgets_use_exact_approved_copy(self):
        # Check the construction path independently of select('setup').
        with patch.object(Dashboard, "select"):
            self.app = App(self.root, demo=True, testing=True)
        self.assert_approved_copy()

    def test_launch_shows_exact_approved_copy(self):
        self.app = App(self.root, demo=True, testing=True)
        self.root.update_idletasks()
        self.assert_approved_copy()

    def test_returning_from_other_pages_preserves_approved_copy(self):
        self.app = App(self.root, demo=True, testing=True)
        for page in ("live", "alerts", "diagnostics"):
            with self.subTest(page=page):
                self.app.view.select(page)
                self.app.view.select("setup")
                self.app.view.render()
                self.root.update_idletasks()
                self.assert_approved_copy()


if __name__ == "__main__":
    unittest.main()
