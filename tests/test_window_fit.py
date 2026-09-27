"""The initial office window must not start outside a 1024x768 desktop."""
import os
import tempfile
import unittest
from unittest.mock import patch
import tkinter as tk
from wakeguard.app import App


@unittest.skipUnless(os.environ.get('WAKEGUARD_GUI_TESTS') == '1' or os.environ.get('DISPLAY'), 'GUI opt-in')
class WindowFitTests(unittest.TestCase):
    def test_initial_window_fits_narrow_office_display(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'WAKEGUARD_DATA_DIR': directory}):
            root = tk.Tk()
            app = None
            try:
                with patch.object(root, 'winfo_screenwidth', return_value=1024), patch.object(root, 'winfo_screenheight', return_value=768):
                    app = App(root, demo=True, testing=True)
                    root.update()
                    self.assertLessEqual(root.winfo_width(), 944)
                    self.assertLessEqual(root.winfo_height(), 668)
                    self.assertTrue(app.view.next_button.winfo_ismapped())
            finally:
                app.quit() if app else root.destroy()


if __name__ == '__main__': unittest.main()
