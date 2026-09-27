"""Disposable text field that records paste content and modifier keys."""

import json
import sys
from pathlib import Path


def main() -> None:
    """Display a disposable text field and record received paste events."""
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    path = Path(sys.argv[1])
    keys = []
    window = Gtk.Window(title="VoicePaste text field verification")
    window.set_default_size(500, 150)
    field = Gtk.TextView()
    window.add(field)

    def pressed(widget, event):
        keys.append(
            {
                "key": Gdk.keyval_name(event.keyval),
                "ctrl": bool(event.state & Gdk.ModifierType.CONTROL_MASK),
                "shift": bool(event.state & Gdk.ModifierType.SHIFT_MASK),
            }
        )
        return False

    def changed(buffer):
        path.write_text(
            json.dumps({"text": buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True), "keys": keys})
        )

    field.connect("key-press-event", pressed)
    field.get_buffer().connect("changed", changed)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    field.grab_focus()
    Gtk.main()


if __name__ == "__main__":
    main()
