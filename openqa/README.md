# BigLinux release gate

Proves that the exact ISO GitHub Actions built can boot, install, reboot, log
in and run its applications - in both firmware modes, without comparing
pixels.

## One file and one script

`release-gate.yaml` is the whole definition. A *plan* is one isotovideo run: a
schedule (the module sequence, in `main.pm`), a machine (the QEMU shape) and
whatever that plan alone needs.

```bash
openqa/production/run-plan.sh \
  --plan live \
  --iso output/biglinux_TESTING_2026-09-08_k618.iso \
  --results /var/tmp/gate/live \
  --password-file /run/user/1000/gate-password
```

The results directory *is* the isotovideo working directory: `testresults/`,
`ulogs/`, `autoinst-log.txt`, `vars.json`, `video.ogv` and the guest disk all
land there, owned by the invoking user. It needs `HDDSIZEGB` plus a fifth -
48 GiB for the default 40 - or isotovideo refuses to start.

There is no openQA server anywhere in this path. isotovideo is the backend
openQA drives; running it directly removes the database, the scheduler, the
asset store and the HTTP hop between a test and its own results, and with them
every failure this project ever had that was not about the ISO: a PostgreSQL
index limit that rejected job creation outright, jobs whose results could not
be copied out of a container, and a password that travelled as a job setting
into an uploaded artifact.

`-e` makes isotovideo's exit status the verdict: 0 when every module ended `ok`
or `softfail`, 100 when no module ran, 101 when one failed.

## What drives the tests

Accessibility, through `lib/atspi.pm` and `data/atspi_probe.py`. A page is
recognised by what it publishes - the accessible name of its table, the label
of its button - so a theme, an icon set, a wallpaper or a translation cannot
turn the gate red. Two needles had been recorded over the *wrong* language
tile, which a green run could never have revealed: the live wizard orders its
tiles by the boot-time locale suggestion, so a recorded click point is a coin
toss between installing Portuguese and installing English.

Three surfaces publish no accessibility tree, and each is a deliberate
exception rather than an oversight:

| Surface | Why | What happens if it breaks |
|---|---|---|
| GRUB | No accessibility of any kind | The first module times out, with the video recorded |
| Plymouth | Same | Same |
| SDDM greeter | Publishes no useful tree | `installed_login.pm` keeps a non-fatal `check_screen`; the greeter *process* and `loginctl` are the real condition |

Nobody should "fix" these with a needle. The static checks in
`.github/workflows/openqa-single-instance-experiment.yml` reject a new
`assert_screen`, `assert_and_click` or `check_screen` anywhere but
`installed_login.pm`, and warn when an active needle is older than half a
year.

The accessibility bus itself needs care, and this cost several days to
understand. `at-spi-dbus-bus.service` is `PartOf=graphical-session.target` and
nothing wants it, so the session that ends takes the bus with it and the
session that starts does not bring it back. Worse, `at-spi-bus-launcher`
unlinks `$XDG_RUNTIME_DIR/at-spi/bus` before binding its own: the launcher
that D-Bus activates inside the live wizard's private session (`dbus-run-session`)
replaces the session's socket and removes it when that bus ends, while the
launcher on the real bus survives and keeps answering `GetAddress` with a path
that no longer exists. So `reset_baseline` trusts the socket, never the
answer, and restarts the launcher when the socket is gone - and
`biglinux-livecd` does the same before handing over to the desktop, because
otherwise every application in the session, Orca included, inherits a dead
address.

## Security is measured, not enforced

`tests/installed_security.pm` reports the installed system's posture as soft
failures with the measured value: whether anything is actually filtering
(`ufw status`, the `INPUT` policy, the nftables ruleset - not merely whether a
unit is enabled), uncommented `NOPASSWD` rules, listening ports, `pacman.conf`
signature levels and mirror schemes, weakened `sysctl` values, SUID files
outside a known list, pending updates and failed units. Turning any item into
a blocker is one line, when that is the decision.

## What a plan costs

Measured on this project's own machine (Ryzen, KVM, 2 vCPU and 4 GiB per
guest), against `biglinux_TESTING_2026-09-08_k618.iso`:

| Plan | Modules | Wall clock | CI bound |
|---|---|---|---|
| live | 1 | 47-65 s | 30 min |
| bios | 12 | see below | 150 min |
| uefi | 12 | see below | 150 min |
| applications-0..3 | 1 each | see below | 90 min each |

The CI bound is what a job may hold a runner for before Actions kills it, not
an estimate: `run-plan.sh` gets ten minutes less than the job, so an overrun
is still collected and reported. A GitHub Free account runs 20 jobs at once,
so six plans in parallel are free of contention with themselves but not with
anything else the account is doing.

A run cannot share the machine with an ISO build: two local runs were killed
by the out-of-memory reaper that way.

## Approval

The same ISO passes twice in a row, without changing code, on `bios` and
`uefi`, and the four application shards aggregate with no missing entry. The
aggregator rejects incomplete shards and provenance mismatches, so a shard
that silently did not run is a failure rather than a smaller number.

## When it breaks

Read `testresults/result-<module>.json` first: `result` and `execution_time`
per module. `autoinst-log.txt` holds isotovideo's own view, including the QEMU
command line - `run-plan.sh` refuses to accept a run whose archived command
line does not contain `-enable-kvm`, because `QEMU_NO_KVM=0` does not
guarantee it: os-autoinst adds the flag only when `/dev/kvm` is readable
*inside* the container, and silently runs TCG otherwise, which would make
every time above a fiction. `virtio_console.log` is what the guest actually
printed, which is where a missing accessibility bus or a mistyped filter shows
up.

## Reading a page's accessibility tree

When a page has to be anchored on something, ask the guest what it publishes.
From a console inside the running guest:

```bash
python3 /tmp/openqa-atspi-probe.py dump-widgets --timeout 30
```

It answers with every named widget - role, name, position, state - and says
whether the walk was truncated. This is how the wizard's pages came to be
identified by the accessible name of their table. It is not available through
`atspi.pm`: a whole tree does not fit through a serial marker, and no test
needs one.
