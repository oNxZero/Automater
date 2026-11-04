# Security reports

For sensitive bugs involving input capture, saved data, command execution or local
session authentication, use [GitHub's private vulnerability reporting](https://github.com/oNxZero/Automater/security/advisories/new)
when it is enabled. Do not attach real recordings or credentials to a public issue.
If that route is unavailable, open an issue asking for a private contact without
including the sensitive details. The maintainer must enable private reporting as
part of the public-release setup.

Ordinary UI/compatibility bugs belong in Issues. Include the version, Linux desktop,
playback mode and a synthetic reproduction. There is no guaranteed response SLA;
this project is maintained on a best-effort basis.

Automater intentionally reads selected physical input devices and can emit desktop
input. Use a trusted installation, run as your regular user, and review workflows
before replaying or sharing them. No telemetry or cloud upload is implemented.
