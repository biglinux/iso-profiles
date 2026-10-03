# openQA harness design

How the release gate in [`openqa/`](../openqa/README.md) decides that an
application or the installer works, and why each rule is there. The code holds
the details; this page is the map.

## Principles

| Area | Rule | Consequence |
|---|---|---|
| Appearance | No needles; screen and pointer APIs are refused in CI | A new colour, wallpaper or icon set needs no new reference |
| Identity | PID, role, accessible name and state, never geometry or window title | A homonymous or hidden target is never acted on |
| Traversal | Bounded by time, node and reference limits; a truncated tree is reported | A partial tree never confirms absence |
| Keyboard | Tab and arrows with focus observed after every key | A trapped focus is a failure, not something `grab_focus` rescues |
| Session | The accessibility bus, display server and toolkit are left as a screen-reader user gets them; the probe only announces itself through `org.a11y.Status.IsEnabled` | The test exercises the shipped environment |
| Applications | Explicit `standard`, `shared-window` and `transient-dialog` contracts | A local exception never weakens the global default |
| Closing | Process exit, window disappearance, exit code and cleanup are separate fields | SIGTERM or SIGKILL never turns a failure into a pass |
| Provenance | Non-empty commit and ISO checksum, every shard present | Mismatched or incomplete results do not aggregate into a pass |

## Ownership of a window

Every application is started by `data/gui_supervisor.sh` in its own session
(`setsid`). A window counts only when it belongs to the launched process scope.
That scope combines three sets:

- the live descendants of the supervised root PID;
- the window PIDs earlier steps already proved;
- the live members of the process group created for that root.

The scope matters because launchers and wrappers often create the interface in a
child that is later re-parented, so a `PPid` walk alone loses it. The process
group comes from `NSpgid` in `/proc/PID/status`. When that line is missing, it is
field 5 of `/proc/PID/stat`, read after the last `)` because `comm` may contain
spaces and parentheses. Only the supervised root may widen the scope to its
group. A PID taken from an arbitrary window stays limited to its own tree, so
desktop services that share a session group are never imported.

The group leader exiting does not mean the application ended while any PID of
the proven scope is still alive.

## AT-SPI cost and timeouts

- Each AT-SPI call is limited to 800 ms, the upstream default
  ([`atspi_set_timeout`](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/func.set_timeout.html)).
  libatspi's per-application startup grace is disabled, because it applies to
  every application a new probe process discovers and could give one call
  15 seconds inside an 8-second wait. The only exception is the privileged
  Calamares PID: it gets up to 5 seconds, removed as soon as its top-level window
  has been seen.
- Subtrees that are not `SHOWING`, or are `DEFUNCT`, are pruned before their
  children are read. `SHOWING` includes the ancestors' state
  ([StateType](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/enum.StateType.html)).
- The application's index in the registry is only a hint. It is tried once, with
  its PID re-checked, and the search then continues from the newest provider to
  the oldest. Short-lived processes move providers between two queries, so the
  index is never an identity.
- Transient read errors are retried within the caller's original deadline. The
  action itself is never repeated, and a persistent error stays inconclusive.
- The launch baseline records only each provider's PID, its number of top-level
  windows and their proxy identities. The full record stays in the guest's state
  file. The serial console carries a short summary, because a full dump
  overflowed the serial capture.

## The smoke session

`smoke-session` keeps one probe process, and one AT-SPI client, for the whole
smoke test:

1. read the baseline and find a new window inside the supervised launch;
2. keep the same accessible object while the window settles;
3. confirm useful accessible content and the `ACTIVE` state;
4. print `READY` with the PID and the exact window identity;
5. wait for the single key the host sends;
6. watch, in the same client, for that window or process to go away.

No key is sent before `READY`. A provider error is never read as the window
disappearing. A fresh client for each phase would start with an empty cache,
and querying unrelated providers again exhausted the deadline before the proven
window was reached.

The probe ends the close phase according to the contract:

- **`process-exit`:** after `READY` it makes no further AT-SPI call. It watches
  only the supervised process scope until the deadline, and always returns a
  structured pass or failure.
- **`window-close`:** a shared service may stay alive, so a disposable AT-SPI
  client watches the exact window. The parent enforces an operating-system
  deadline, and requires an explicit witness that the window is gone, or proof
  that the process exited. A hang, invalid output or an incomplete read is a
  structured failure.

An empty window is a failure. A traversal that could not finish is inconclusive
and blocks the gate: the deadline expired mid-walk, a node or reference limit
was hit, or there was a cycle, a missing child or a provider error. If the
deadline expires between two complete scans that both found nothing, the
confirmed absence stands.

## First-run surfaces

Some applications open a dialog over their main window on first start: GIMP,
the LibreOffice components, Qt Designer, BigOCR, Big Video Converter, the
WebApps Manager, HP Device Manager and Restore Settings. Their contracts set
`dismiss_auxiliary: true`. Up to three such surfaces may then be closed in
sequence, each only after an active window of the same PID and launch is
observed:

- a separate dialog gets `Alt+F4`;
- a libadwaita overlay inside the same top-level gets `Escape`.

After that, the application's own exit shortcut is sent. Every preliminary
action is recorded as `pre_close_action`, and no other application gets one
inferred for it.

Two contracts follow the application's own definition. KRunner hides on
`Escape` and its service keeps running, so the exact runner window must
disappear. qBittorrent maps `Ctrl+Q` to `QApplication::exit()`, so the
process must exit with status zero.

## The installer

The GTK frontend of the live installer starts Calamares through `sudo`, so the
Qt installer is not in the user's process group. The handoff is accepted only
when one process matches all four of these:

- real executable `/usr/bin/calamares`;
- real and effective UID 0;
- the unique `DESKTOP_STARTUP_ID` the launch set and the product wrapper forwards;
- the same PID and `starttime` on two reads of `/proc`.

From then on, pages are found only under that PID. Neither process names nor
window titles nor a new window anywhere on the desktop prove the transition. The
helper (`data/process_handoff.py`) only reads `/proc`.

Calamares pages are found by a positive witness: the search stops at the first
control whose role, name and PID all match. Roles are read before names, and
names are read only for the roles the anchor asks for. A control that is hidden,
insensitive, ambiguous or outside the PID still blocks. Every other widget
query keeps requiring a complete tree. The welcome, users, summary and finished pages
are QML from the BigLinux branding in
[biglinux-livecd](https://github.com/biglinux/biglinux-livecd), and their
anchors use the strings of its `i18n.js`: the welcome page is identified by its
"Choose the language" selector, the finished page by its "Restart system"
button.

When launching the installer fails, `installer_launch`'s `post_fail_hook`
attaches observations only:

- the Calamares, Python, `dbus-launch` and `sudo` process topology, without
  arguments or environment;
- the launch logs;
- up to 32 MiB of the root session log, copied without following symlinks into a
  private temporary file;
- metadata of `/run/biglinux-live/calamares`.

It never starts, restarts or reconfigures a service. The startup token is
recorded only as present or absent.

## References

- os-autoinst `testapi`: https://open.qa/api/testapi/
- Running `isotovideo` directly: https://open.qa/docs/#_run_isotovideo_directly_in_the_ci_runner
- AT-SPI `Accessible`: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/class.Accessible.html
- AT-SPI `grab_focus` and `do_action` prove neither keyboard reachability nor a
  post-condition:
  https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Component.grab_focus.html,
  https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Action.do_action.html
- Desktop Entry keys: https://specifications.freedesktop.org/desktop-entry/latest/recognized-keys.html
- Orca's test recorder: https://github.com/GNOME/orca/blob/main/src/orca/dbus_service.py
- GNOME HIG on accessibility and keyboard use:
  https://developer.gnome.org/hig/guidelines/accessibility.html
