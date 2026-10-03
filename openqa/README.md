# openQA release gate

Before a BigLinux ISO is published, it has to boot, install, reboot and
launch its applications. That is checked here by running the
[os-autoinst](https://github.com/os-autoinst/os-autoinst) test engine,
`isotovideo`, directly in a pinned container. There is no openQA server. Each
plan is a single `isotovideo` run, and its exit status is the verdict.

Every check reads the accessibility tree (AT-SPI) and the guest's serial
console. Screenshots and video are kept for diagnosis only: no needle exists,
and `production/check-nonvisual.py` refuses screen matching or pointer input in
test code. A new theme, wallpaper or icon set therefore needs no new
reference images. Losing an accessible name, a state or keyboard navigation is
a real regression and fails the gate.

## What the gate checks

| Plan | Firmware | Schedule |
|---|---|---|
| `bios` | BIOS | live session, six key applications, install, first boot, login, installed system |
| `uefi` | UEFI | the same, without the application sample |
| `applications-0` … `applications-3` | BIOS | every graphical desktop entry of the live ISO, split in four shards |
| `live` | BIOS | live session only; local use, not part of the gate |

The installed-system modules check SDDM login, system health, security posture
(reported, not blocking) and the installed applications listed under
`critical` in the policy. GRUB is not tested on its own: if it is broken,
nothing boots and the first module times out.

## Where each setting lives

| File | Defines |
|---|---|
| `release-gate.yaml` | plans, QEMU machines, shards, time limits and which plans form the gate |
| `main.pm` | the module sequence of each schedule |
| `application-policy.yaml` | exclusions, aliases, per-application close contracts and the installed-application selection |
| `openqa-image.txt` | the `isotovideo` image, pinned by digest in this repository's GHCR mirror |
| `openqa-image-source.txt` | the reviewed upstream image that `mirror-openqa-image.yml` copies |
| `production/run-plan.sh` | the fixed `isotovideo` variables; the only reader of `release-gate.yaml` |
| `production/check-harness.sh` | every check that needs neither a VM nor a GUI |

`build-iso.yml` calls `openqa.yml` (the gate), which calls `openqa-report.yml`.
`openqa-nonvisual-checks.yml` runs on pull requests. `mirror-openqa-image.yml`
is run by hand to import a new image.

## Running a plan

```bash
openqa/production/run-plan.sh \
  --plan bios --iso /path/candidate.iso \
  --results /var/tmp/gate/bios --password-file /run/user/1000/gate-password \
  --build candidate --commit "$(git rev-parse HEAD)" \
  --iso-sha256 "$(sha256sum /path/candidate.iso | cut -d' ' -f1)"
```

A UEFI plan also needs `--uefi-code` and `--uefi-vars` (OVMF without Secure
Boot). The host needs Docker and a usable `/dev/kvm`, and the run fails if QEMU
did not use KVM. The results directory needs room for the guest disk, HDDSIZEGB
plus a fifth, so 48 GiB for the default 40. `run-plan.sh --list` prints the
plans CI turns into its job matrix.

The password is read from a file mounted read-only into the container. It is
never a job variable, because `isotovideo` writes `vars.json` unredacted and
that file is uploaded.

## The application smoke test

The same smoke test runs on the live ISO and on the installed system
(`lib/application_smoke.pm`):

1. launch the installed desktop entry;
2. wait for a window owned by the launched process tree;
3. find at least one useful accessible object: a named control, text, an action
   or a value;
4. send one normal shortcut, `Alt+F4` by default;
5. confirm the outcome the entry's contract declares.

The default contract requires the window and the process to end, with exit
status zero. A resident service (`shared-window`) only has to close the window
that was observed. A dialog (`transient-dialog`) may exit only with the
cancellation codes listed for it. A crash, a missing window or a missing
accessible object fails. So does an exit code outside the list, or any need to
kill the process. The test does not walk every function of an application.

From launch to close a single AT-SPI client is kept alive (`smoke-session` in
`data/atspi_probe.py`). It holds on to the exact window it proved, and the host
sends its key only after the probe reports `READY`.

The policy adapts to the ISO instead of listing required packages:

- an entry the ISO does not ship is reported as not applicable, never as passed;
- `TryExec`, `Hidden`, `OnlyShowIn` and `NotShowIn` decide whether an entry
  applies to the session;
- `Terminal=true` commands and services without a window are out of scope;
- an entry that is present but broken is an error;
- `requires` makes an entry not applicable when the hardware is absent (camera,
  ALSA card, UEFI variables, an X11 session); a failing probe is still a failure;
- `exclude` lists helpers, handlers and bootstrap installers, each with its
  reason. `steam.desktop` is there because it installs the Steam client instead
  of opening it.

Optional job variables, for a plan's `settings`:

| Variable | Default | Range |
|---|---|---|
| `BIGLINUX_APPLICATION_FILTER` | all | comma-separated desktop IDs |
| `BIGLINUX_APPLICATION_TIMEOUT` | 30 | seconds to open a window |
| `BIGLINUX_APPLICATION_SETTLE_SECONDS` | 2 | 0–10 |
| `BIGLINUX_APPLICATION_CONTENT_TIMEOUT` | 10 | 1–120 |
| `BIGLINUX_APPLICATION_CLOSE_TIMEOUT` | 15 | 1–120 |
| `BIGLINUX_APPLICATION_CLOSE_KEY` | `alt-f4` | `alt-f4`, `ctrl-q`, `esc` |
| `BIGLINUX_DEEP_APPLICATION_TESTS` | 0 | 1 enables the task tests below |

## Adding or removing a program

Every graphical desktop entry the ISO ships is tested; there is no list of
programs to include. Adding a package to a profile adds its entries to the
next run. `application-policy.yaml` only records the exceptions, keyed by the
desktop ID: the path under `/usr/share/applications`, such as
`bigcontrolcenter/hplip.desktop`.

A program that opens and closes like an ordinary window needs no entry. Give it
one under `contracts` when it does something else, and say why in `reason`:

```yaml
  - desktop_id: bigcontrolcenter/hplip.desktop
    kind: shared-window          # standard (default), shared-window or transient-dialog
    dismiss_auxiliary: true      # a dialog opens over the main window first
    reason: With no printer configured, HP Device Manager raises a dialog over its window
```

| Field | Use it when the program |
|---|---|
| `kind: shared-window` | keeps a service running after its window closes |
| `kind: transient-dialog` | is a dialog that exits on cancel; list its codes in `allowed_exit_codes` |
| `close_key` | quits with `ctrl-q` or `esc` rather than `alt-f4` |
| `dismiss_auxiliary` | shows a welcome or first-run dialog before its main window |
| `content_timeout`, `close_timeout` | needs more than 10 s to fill its window or 15 s to quit (1–120) |
| `requires` | needs `alsa-card`, `video-device`, `uefi-variables` or `native-x11` |

To test a program on the installed system as well, add it to `critical` with a
short `functional_test` label (letters, digits, `.`, `_` or `-`).

To stop testing a program, add it to `exclude` with a `reason` that says why it
cannot be tested or what has to be fixed first, and keep the list in
alphabetical order. An excluded entry must not also appear under `contracts` or
`critical`; remove it from there. The program stays in the ISO and the report
lists it as excluded with its reason.

Before pushing, `openqa/production/check-harness.sh` validates the policy and
rejects duplicates and overlaps. To watch one program without running a whole
shard, add a plan with the `applications` schedule to a local copy of
`release-gate.yaml`, set `BIGLINUX_APPLICATION_FILTER` to part of its desktop
ID, and run it as shown in [Running a plan](#running-a-plan).

## Selectors and keyboard

Selectors combine PID, role and the localized accessible name. An ambiguous
match fails. An AT-SPI object path identifies a widget within one run only;
it is not a stable ID across releases.

Activation goes through the keyboard. The test sends Tab and the arrow keys,
reads the focus after every key, and stops on a cycle or after a step limit. It
never calls `grab_focus`. A required wait must be confirmed. When a query has
to prove that something is absent, it needs a complete scan: a bus error, a
timeout, a node limit or a partial tree is a blocking inconclusive result.

The harness does not restart the accessibility bus. It does not force X11, a
toolkit plugin or accessibility variables onto an application either: an entry
is launched with the environment the session gave the systemd user manager,
the one Plasma's own launcher passes on, not with the serial console's login.
Before every launch the probe sets `org.a11y.Status.IsEnabled`, the property an
assistive technology sets and applications watch; Qt programs on the installed
system publish no tree without it. `ScreenReaderEnabled` is left alone. Fixtures
are prepared through the serial console, and the action under test always goes
through the GUI.

To inspect a window's tree from a console inside the guest:

```bash
python3 /tmp/openqa-atspi-probe.py dump-widgets \
  --state /tmp/openqa-atspi-baseline.json --timeout 30
```

## Task tests and Orca (opt-in)

With `BIGLINUX_DEEP_APPLICATION_TESTS=1` the installed system also runs
`tests/nonvisual_tasks.pm` and the extended Brave check:

- **Kate:** saves a text, which is read back from disk.
- **Konsole:** runs a command whose output file is checked.
- **Dolphin:** renames a file.
- **Brave:** operates a local fixture by keyboard.

Each task also checks what Orca said about it. `data/orca_probe.py` starts an
instrumented Orca with `--replace`. Its speech log comes through the upstream
`SetLogFileForTesting(s,s)->b` D-Bus method, which exists only when Orca is
started with `ORCA_TEST_RPC_SECRET`. The secret stays in that process's
environment. If the method is missing, the task is blocked and the report says
why. This proves what Orca's speech presenter produced, not audible speech or
braille output.

These tests close their windows with `atspi->terminate_window`, which escalates
from the AT-SPI close action through shortcuts to a signal. That cleanup is
recorded separately and never counts as the application passing.

## Results and reports

Each plan's results are `testresults/`, `ulogs/`, `autoinst-log.txt` and
`virtio_console.log`. The application shards are combined by
`production/aggregate-application-results.py`. It requires every shard, one
consistent commit and ISO, and real accessibility evidence for each pass.

A report is published on success, on failure and when a plan never started:
`RESULTADO.md` (also the Actions summary), `RESULTADO.json`, HTML and, for the
whole run, a PDF. Their language is Brazilian Portuguese, for the team that
reads them. [docs/openqa-reports.md](../docs/openqa-reports.md) describes the
publication contract.

## Checking the harness

```bash
python3 -m pip install -r openqa/report/requirements.txt
openqa/production/check-harness.sh
```

This is the list the pull-request workflow and the gate's `static` job run.
`t/lib` holds test doubles for the Perl contract tests only; never put it on the
path of a real `isotovideo` run. The harness also has a real GTK and AT-SPI
integration test (`integration/accessible_smoke.py`), which CI runs under Xvfb.

## Known limits

The gate does not certify the system for screen-reader users. It does not test
Orca in the live installer, the SDDM greeter, unlocking, authorization prompts,
error recovery or audible output. The login module only proves that
authentication and the session work. The boot, login and installer modules
target the KDE Plasma and SDDM profiles; the application smoke test reads only
the desktop entries and is not tied to KDE. Testing with blind users is still
needed.

The design behind these rules is in [docs/openqa-design.md](../docs/openqa-design.md).
