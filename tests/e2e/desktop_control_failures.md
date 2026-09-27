# Desktop integration failure cases

The desktop end-to-end run produces a JSON report with service state, microphone stream ownership, application lifecycle transitions, manual control state, and actual paste results from disposable test windows. Microphone probe audio is discarded.

- A second recording app shares the microphone while VoicePaste keeps listening.
- Playback-only audio or VoicePaste's own input causes an automatic pause.
- OBS opens without an active microphone source and fails to pause dictation.
- VoicePaste starts while another recorder is already using a microphone.
- One of two competing recorders closes and dictation resumes before the remaining recorder releases capture.
- Automatic resumption overrides manual disable, including after a service restart.
- The watcher restarts the listener repeatedly or leaves a stale listener socket.
- Pausing during dictation loses captured text, pastes into the other app, or leaves the microphone open during transcription.
- The dock launcher or its enable, disable, and status actions fail to reach the service, or installation overwrites existing favorites.
- Missing audio monitoring silently allows recording when exclusivity is unknown.
- Terminal paste sends Ctrl+V, inserts a literal control character, or presses Enter and executes input.
- Ordinary text fields receive the terminal shortcut.
- Missing focus information prevents clipboard fallback, or an application switch sends paste to an unintended window.

Native terminal windows are identified through X11 window class. Accessible embedded terminals can report their terminal role through AT-SPI. Tests use disposable terminal and editor windows and verify key modifiers and received text; the previous focused window and clipboard are restored.

- Neovim normal mode treats dictated text as commands, changes modes unexpectedly, or damages existing buffer content.
- Neovim insert mode or LazyVim mappings lose multiline text, punctuation, or Unicode during bracketed paste.

The Neovim checks use a disposable buffer and explicit test server socket to read back its contents after actual terminal clipboard paste. They exercise normal and insert modes with clean Neovim and the installed LazyVim configuration.

- Notifications from reminders, errors, and manual controls appear under different application sources.
- A custom notification title changes the application identity or loses the desktop-entry association.

The notification check monitors VoicePaste's own D-Bus notification calls and verifies a shared application name and desktop-entry hint, including different message titles. Its JSON artifact records the application identity registered by GNOME.
