# Public-preview release readiness

The repository remains private until the owner explicitly publishes it. Version
0.10.0 prepares the code, documentation and contribution flow for a public preview;
this document does not claim hardware/game acceptance that has not been tested.

## Prepared in the repository

- MIT license, project metadata and documentation/issue URLs.
- Short current-feature README, separate installation/user guides and archived
  release notes; an offline Getting started guide and theme gallery inside Studio.
- Eleven complete themes, color overrides and preference validation. Appearance
  remains outside portable scripts and preserves editor state.
- Fixes/regressions for grouping subsets, duplicate order/identities, custom group
  colors, name collisions, blocked opens, note draft protection, text Undo, action
  creation and retained run results after failed playback validation.
- Test matrix for Python 3.11/3.14, lint/format checks, builds and native shutdown
  checks. Actions use the maintained v7 releases verified during this audit.
- Public bug/feature templates and contribution/security reporting instructions.
- Root recordings excluded from Git; source/wheel contents checked for personal
  workflow data. No real user input is used in committed fixtures/screenshots.

## Complete on real desktops before a stable-release claim

1. Record/replay keys, overlapping holds, mouse buttons, XY reports and wheel input
   on X11 and KDE/GNOME Wayland. Check permission-denied/disconnected device paths.
2. Exercise F12 and pause/resume while holding modifiers/buttons. Verify cleanup is
   received by the actual destination, including target closure and normal quit.
3. Check cursor reset on multiple/scaled monitors, approved/denied portal sessions,
   two loops, interruption, and the overlay in a fullscreen application.
4. Verify acceptance in each supported target game. Test X11 background separately;
   never infer game acceptance from a generic receiver. Test a new Gamescope game
   session on a GPU-capable host, including launch errors and session cleanup.
5. Fresh-install from a clean checkout/account using the documented steps. Test
   first-run setup, legacy import, capture/append/re-record, Save As, recovery after
   an interrupted session, and all themes at 1000×680 and a wide screen.

The development sandbox has no physical input/uinput devices or accessible Vulkan
GPU. Those checks remain manual; automated results are in [VALIDATION](VALIDATION.md).

## Owner-controlled publication

After reviewing the actual files and the manual checks:

1. Decide whether the initial release is a public preview or a stable release;
   retain the compatibility limits in either case.
2. Review repository history, screenshots and artifacts for personal data.
3. Make the repository public, enable Issues/private vulnerability reporting and
   review branch protection for the Checks workflow.
4. Publish a version tag/release with the tested source/wheel and concise release
   notes. Packaging a Linux installer or signing binaries is separate future work.

Changing visibility, publishing a release and sending announcements are not done
by the local readiness audit.
