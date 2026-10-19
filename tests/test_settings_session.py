"""Native close-veto ownership, parent teardown, and accepted literal baseline."""
import time
import unittest
from types import SimpleNamespace
from open_law_lens.settings_session import SettingsSession, close_settings_before_parent
from gi.repository import Adw, GLib, Gtk


def drain():
    end = time.monotonic() + .1
    while time.monotonic() < end:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(.005)


class SettingsSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check():
            raise unittest.SkipTest("GTK display unavailable")
        Adw.init()
        cls.app = Adw.Application(application_id="org.synthetic.OpenLawLens.SettingsSessionTests")
        cls.app.register(None)

    def setUp(self):
        self.state = [" literal α\t{{placeholder}}\n"]
        self.w = Adw.ApplicationWindow(application=self.app)
        self.w._session = SettingsSession(self.w, lambda: tuple(self.state))
        self.w.connect("close-request", self.w._session.close_request)
        self.owner = SimpleNamespace(window=self.w)
        def accepted(_window):
            self.owner.window = None
            return False
        self.w.connect_after("close-request", accepted)
        pass
        self.w.present()
        drain()

    def tearDown(self):
        if self.w._session.dialog:
            self.w._session.dialog.response("keep")
        self.w.set_focus(None)
        drain()
        self.w.destroy()
        drain()

    def test_parent_close_veto_keeps_owner_until_clean_close(self):
        baseline = self.w._session.baseline
        self.state.append("unsaved")
        self.assertTrue(close_settings_before_parent(self.app))
        self.assertIs(self.owner.window, self.w)
        self.assertFalse(self.w._session.closed)
        dialog = self.w._session.dialog
        self.assertTrue(dialog.has_response("keep"))
        self.assertTrue(dialog.has_response("discard"))
        self.assertFalse(dialog.has_response("save"))
        dialog.response("keep")
        self.assertEqual(self.w._session.baseline, baseline)
        self.assertTrue(self.w.get_visible())
        self.w._session.accept()
        self.assertFalse(close_settings_before_parent(self.app))
        self.assertIsNone(self.owner.window)
        self.assertTrue(self.w._session.closed)

    def test_discard_never_saves_and_does_not_revert_previous_accept(self):
        self.state.append("saved revision")
        self.w._session.accept()
        accepted = self.w._session.baseline
        self.state.append("later unsaved change")
        self.w.close()
        self.assertIs(self.owner.window, self.w)
        self.w._session.dialog.response("discard")
        self.assertFalse(self.w.get_visible())
        self.assertIsNone(self.owner.window)
        self.assertEqual(self.w._session.baseline, accepted)
