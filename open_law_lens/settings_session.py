"""Application-local dirty-close guard; Save never continues a close."""
import gi

gi.require_version("Adw", "1")
from gi.repository import Adw


def close_settings_before_parent(application):
    """Veto parent teardown until each owned settings close is accepted."""
    for window in list(application.get_windows()):
        if isinstance(getattr(window, "_session", None), SettingsSession):
            window.close()
            if window.get_visible():
                window.present()
                return True
    return False


class SettingsSession:
    def __init__(self, window, snapshot, immediate_note=""):
        self.window, self.snapshot = window, snapshot
        self.baseline = snapshot()
        self.closed = False
        self._discard = False
        self.dialog = None
        self.immediate_note = immediate_note

    def accept(self):
        self.baseline = self.snapshot()

    def close_request(self, *_):
        if not self._discard and self.snapshot() != self.baseline:
            if self.dialog is None:
                dialog = Adw.MessageDialog(transient_for=self.window, heading="Discard unsaved changes?",
                    body="Only changes since the last successful Save will be discarded." + self.immediate_note)
                dialog.add_response("keep", "Keep Editing")
                dialog.add_response("discard", "Discard Unsaved Changes")
                dialog.set_default_response("keep")
                dialog.set_close_response("keep")
                dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
                def response(_dialog, choice):
                    self.dialog = None
                    if choice == "discard":
                        self._discard = True
                        self.window.close()
                dialog.connect("response", response)
                self.dialog = dialog
            self.dialog.present()
            return True
        self.closed = True
        return False
