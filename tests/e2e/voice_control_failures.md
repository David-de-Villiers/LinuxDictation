# Voice control failure cases

The end-to-end replay uses actual Vosk and Whisper models with locally synthesized speech, the listener's PCM input, its Unix control socket, transcript delivery, and recorded notification events. The report records inputs, detected events, transcript text, and assertions so a run can be repeated and inspected.

- Ordinary idle speech or silence accidentally starts recording.
- “Start dictation” fails to activate, or recognition latency loses the first dictated words.
- “Thank you” fails to stop, leaks into pasted text, or consumes words before the command.
- A command split across microphone frames fails to match.
- Silence stops recording before ten seconds, fails to stop at ten seconds, produces a reminder before five seconds, repeats the reminder throughout one pause, or fails to reset both timers after resumed speech.
- Recording stops at the old 30-second or 120-second limits.
- Ctrl+backtick starts a second process instead of stopping the active recording, or repeated shortcut input starts a new recording during transcription.
- A second listener steals the socket, a stale socket blocks restart, or stop while idle unexpectedly starts recording.
- Empty recording overwrites the clipboard or the last transcript.
- Multiple recording sessions leak command recognition state or raw audio.
- Long recordings consume memory proportional to audio duration or overflow a WAV size limit.
- Transcription chunk boundaries lose words at the beginning of a sentence or duplicate neighboring speech.
- Audio overflow or transcription failure silently loses a recording or kills subsequent sessions.
- Listener shutdown leaves a usable stale socket or raw audio on disk.

The desktop check verifies that GNOME maps Ctrl+backtick to the socket toggle helper and that the user service runs the listener. Actual microphone recognition remains dependent on pronunciation and ambient sound; replay establishes a repeatable baseline. Continuous speech with pauses shorter than five seconds verifies recording beyond two minutes, and a separate ten-second pause verifies automatic completion.
