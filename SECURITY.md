# Reporting security bugs

Please don't post sensitive recordings, credentials or exploit details in a public
issue. Use [GitHub's private reporting
form](https://github.com/oNxZero/Automater/security/advisories/new) if it's available.
If it isn't, open an issue asking how to get in touch privately and leave out the
sensitive details.

This includes bugs involving input capture, saved files, command execution or access to
a game session. Ordinary UI bugs can go in Issues. Include your version and steps to
reproduce with a small example that contains no personal input. There is no guaranteed
response time.

Automater reads the input devices you select and can send keyboard and mouse input. Run
it as your regular user and review workflows before running or sharing them. The app has
no telemetry or cloud upload.

Keep `portal-pointer.json` private. It holds the desktop's saved pointer approval
and is not part of a workflow export.
