"""Query focused terminal roles through the system's optional AT-SPI bindings."""

from __future__ import annotations

import sys


def main() -> None:
    """Inspect only accessibility states and roles, without reading field content."""
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    desktop = Atspi.get_desktop(0)
    pid = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        if pid and app.get_process_id() != pid:
            continue
        pending = [(app, False)]
        visited = 0
        while pending and visited < 500:
            item, in_terminal = pending.pop()
            visited += 1
            states = item.get_state_set()
            in_terminal = in_terminal or item.get_role() == Atspi.Role.TERMINAL
            if states.contains(Atspi.StateType.FOCUSED) and in_terminal:
                print("terminal")
                return
            if item.get_role() in {Atspi.Role.FRAME, Atspi.Role.WINDOW} and not states.contains(Atspi.StateType.ACTIVE):
                continue
            pending.extend((item.get_child_at_index(i), in_terminal) for i in range(min(item.get_child_count(), 100)))


if __name__ == "__main__":
    main()
