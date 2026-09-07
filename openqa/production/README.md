# BigLinux openQA release gate

Owns the release-blocking openQA path from the private ISO artifact to the
publication decision.

Hard invariants:

- BIOS, UEFI, and four application shards run in independent `ubuntu-24.04` jobs.
- Each job starts one local openQA single-instance container and one local KVM worker.
- `/dev/kvm` and the archived QEMU command must prove KVM; TCG is never accepted.
- The ISO is verified from the build artifact or an existing release before use.
- A failed, cancelled, incomplete, or unverifiable firmware job or application
  shard blocks publication.
- The build job receives no openQA credentials because this architecture has none.

Run a new candidate with `publish_release=false`:

```bash
gh workflow run "Build ISO" --repo biglinux/iso-profiles \
  --ref openqa-single-instance-experiment \
  -f edition=kde -f kernel=lts -f manjaro_branch=stable \
  -f big_branch=stable -f publish_release=false
```

Validate a change with:

```bash
git diff --check
bash -n openqa/production/*.sh openqa/development/*.sh data/*.sh
shellcheck -x openqa/production/*.sh openqa/development/*.sh data/*.sh
actionlint
```

---

## What the gate closes

The release decision must prove that the exact ISO built by GitHub Actions can
boot, install, reboot, log in, and pass health checks in both supported firmware
modes. It also runs the complete recursive `.desktop` audit in four application
shards and runs selected critical applications after installation. The
aggregator is mandatory: it rejects missing entries, incomplete shards,
provenance mismatches, and any failed launch.

```text
Build ISO
   |
   +-- private artifact: ISO + checksums
   |
   +-- BIOS runner (ubuntu-24.04)
   |      local web UI + scheduler + database
   |      local worker --device=/dev/kvm
   |      one release_bios job
   |
   +-- UEFI runner (ubuntu-24.04)
          local web UI + scheduler + database
          local worker --device=/dev/kvm + OVMF
          one release_uefi job
   +-- four application runners (ubuntu-24.04)
          one local openQA instance and one KVM worker per shard
   |
   +-- aggregate application metrics
   |
   +-- publish only when build, BIOS, UEFI, and application coverage are successful
```

The container image is the digest-pinned value in
[`../openqa-image.txt`](../openqa-image.txt). It is the official openQA
single-instance image used by the local development bridge. The container is
stopped and removed at the end of every job; its database, assets, and results
are not reused by another run.

The gate schedules through `SCENARIO_DEFINITIONS_YAML`, which openQA's own
documentation still labels experimental and free to change incompatibly. The
digest pin is what keeps that from breaking a release: raising the image is
therefore never a routine bump. Run one full firmware plan on a known ISO with
the new image before the pin is updated, and expect
[`../scenario-definitions.yaml`](../scenario-definitions.yaml) to need changes
if the schema moved.

## Inputs and artifacts

The reusable workflow receives `candidate_artifact`, `iso_filename`, `version`,
and `build_id` from `build-iso.yml`. The manual dispatch path downloads either
the direct release ISO or every numbered `.7z.*` part, verifies the complete
sequence, extracts the ISO, and checks both checksum files.

The build publishes no public asset before the gate. The same artifact is
downloaded by every runner, so all firmware and application jobs test the same
bytes.

Every runner job uploads a uniquely named diagnostic artifact containing the
ISO identity, resource measurements, container logs and metadata, job IDs,
openQA archives, module details, screenshots, video when generated, KVM
evidence, and the HTML report. `schedule-release-gate.sh` redacts every
`_SECRET_*` value from the JSON it writes there first: openQA hides those
variables in its web UI but returns them verbatim from the scheduled-product
API, and this directory is a downloadable artifact. Collection runs after failures and never changes
the original test result to success.

## Local openQA lifecycle

`start-container.sh` is the entry point inside the pinned image. It grants the
worker the host KVM group, starts the official single-instance bootstrap, and
skips unrelated openSUSE test downloads. The workflow waits for all of these
observable conditions before scheduling:

1. the local API responds;
2. the scheduler process is present;
3. exactly one connected worker advertises `biglinux-kvm`;
4. that worker can read and write `/dev/kvm`.

The scheduler helper is
[`schedule-release-gate.sh`](../development/schedule-release-gate.sh). A
non-dry invocation requires `--firmware bios`, `--firmware uefi`, or
`--applications-shard INDEX 4`, submits
`SCENARIO_DEFINITIONS_YAML` through the official local `openqa-cli` API, and
polls the returned product and job JSON. It never uses SSH, a remote API key,
or a server URL.

The checked-out sources are mounted read-only at `/workspace-source`; the
container entrypoint copies them to writable `/workspace` before openQA checks
out the pinned `TEST_GIT_REFSPEC`. The job records the full `GITHUB_SHA`, uses
the copied scenario file and needles, and sets `QEMU_NO_KVM=0`. BIOS uses the
`release` schedule, UEFI uses `release_uefi`, and application runners use the
`applications` schedule with the matching deterministic shard.

The four application payloads are checked by
[`aggregate-application-results.py`](aggregate-application-results.py). The
aggregator recomputes the SHA-256 shard assignment, verifies the inventory hash,
checks explicit policy classifications, requires every launchable entry exactly
once, and fails on any application result other than `passed`. Per-entry metrics
include RSS, PSS, process count, AT-SPI state, launch method, and cleanup state.

## KVM and UEFI evidence

The runner first checks the character device, read/write access, `kvm-ok`, and
a minimal QEMU process started with `-accel kvm`. The UEFI job installs `ovmf`
when needed and selects a matching non-Secure-Boot pair in this order:
`OVMF_CODE_4M.fd` with `OVMF_VARS_4M.fd`, then the legacy `OVMF_CODE.fd` with
`OVMF_VARS.fd`. It records the selected paths and mounts per-job copies into
the worker container. The UEFI machine uses Q35 and keeps Secure Boot disabled.

After the openQA job, [`verify-kvm-results.sh`](verify-kvm-results.sh) requires
positive evidence such as `-enable-kvm`, `-accel kvm`, or `-accel=kvm` in the
archived `autoinst-log.txt`. It rejects TCG evidence, contradictory logs, and
logs without positive KVM evidence.

## Application audit

The `applications` schedule recursively inspects application desktop entries.
It starts programs through the existing safe desktop-entry launcher, prefers
AT-SPI semantics, records process memory, continues after individual failures,
and uploads one compressed metrics payload per shard. The policy file explicitly
classifies services, helpers, aliases, and invalid entries. Screenshots are not
application assertions; the normal openQA video remains the visual evidence.
Critical installed applications additionally receive an AT-SPI action, close
request, process-exit, and exit-code check.

## Manual local investigation

For an interactive investigation, start the disposable MCP bridge with an
existing ISO:

```bash
./openqa/development/start-mcp.sh /absolute/path/to/biglinux.iso
```

This is local development only. It uses the same pinned image, requires KVM,
binds its endpoint to loopback, and is not a second production implementation.

## How the gate decides what it sees

Everything that publishes an accessibility tree is driven through AT-SPI: the
live wizard (GTK4/libadwaita), the BigLinux installer launcher and its dialogs
(GTK4), Calamares itself (Qt), and every application in the audit. A page is
recognised by a control only that page owns - the "Região" selector, the
"Modelo de teclado" label, the "Apagar disco" radio - never by a picture of it.
`openqa/lib/calamares.pm` keeps that map in `%PAGE_ANCHORS`.

This is not a style preference. A needle records one build's pixels, so a new
theme, a translated string or a reordered grid turns the gate red for no defect
at all; worse, a needle that still matches after the layout moved sends a click
somewhere else. Both happened here: five needles had to be re-recorded for one
build, and the 2026-08-04 language needle had its click point over what later
builds render as "English, United States" - a green run would have installed
the wrong language.

Three things have no accessibility tree and stay outside this rule:

| Surface | Why | How it is covered |
| --- | --- | --- |
| GRUB | Boot loader, no session, no AT-SPI | Not asserted: if it breaks, the first module times out with the video recorded |
| Plymouth | Same | Same |
| SDDM greeter | Its QML greeter publishes nothing useful | The greeter *process* is the condition; the screenshot is evidence only |

The workflow enforces this: a new `assert_screen`, `assert_and_click` or
`check_screen` outside that last row fails the static validation, together with
an audit that rejects a needle no test uses and a tag no needle answers.

`openqa/needles/` holds exactly what those two surfaces need - four files for
the live wizard and one for the greeter, answering five tags. The other 35
files and 24 tags were deleted once the installer moved to AT-SPI; a needle
kept "just in case" is a needle nobody re-records, and the audit above now
fails the build rather than let one accumulate again. It also prints a warning
for any surviving needle older than 180 days, so the re-recording happens on a
quiet day instead of in the middle of a release.

## When a needle stops matching

A needle describes one build's pixels. When the ISO changes a wizard page, the
job stops at that page and every later module is skipped, which looks alarming
and usually is not: the gate is doing its job.

The loop that fixes it, cheapest step first:

1. Run only the live schedule against the new ISO. It loads a single module and
   fails within minutes on the first stale needle, instead of spending an hour
   to tell you the same thing:
   `BIGLINUX_SCHEDULE=live` with `TEST=release_bios`.
2. Take the last screenshot the failing module recorded — that *is* the screen
   the needle should describe:
   `ls -v /var/lib/openqa/testresults/*/<job>*/<module>-*.png | tail -1`.
3. Add a new needle named after the day (`<tag>-YYYYMMDD.json/.png`) carrying
   the **same tag** as the old one. openQA accepts any needle with the tag, so
   the previous file keeps older ISOs working - unless its click point now
   lands on a different control, in which case delete it instead of keeping it.
   Two needles under one tag are two candidates, and openQA picks by pixel
   score, not by date: the old language needle clicked at (513, 255) and the
   new one at (242, 257), the first of which is "English, United States" on
   this build.
4. Anchor it on translated labels that identify the page, not on values.
   A needle over "Região:" and "Área:" survives a changed default timezone; a
   needle over "New York" does not.
5. Re-run the plan. Each pass reveals at most one stale needle, so expect one
   round per changed page.

A needle that matches the wrong control is worse than one that matches nothing:
the 2026-08-04 language needle had its click point over the middle column,
which in a later build is "English, United States". Always check what the
click point lands on before trusting a green run.

## What the gate measures but does not block on

`openqa/tests/installed_security.pm` runs on the installed system and reports
its security posture as **soft failures**: passwordless sudo entries, services
listening beyond loopback, whether anything actually filters incoming traffic,
unsigned package databases, plain-HTTP mirrors, weakened
`kptr_restrict`/`dmesg_restrict`, AppArmor running with `audit=0`, the LUKS
generation when the disk is encrypted, and how many updates are already pending
on a fresh install.

The firewall item measures filtering, not configuration, and the difference is
the whole point: `ufw` is listed in `enable_systemd`, so `systemctl is-enabled
ufw` says `enabled` on every install while the policy stays `ACCEPT` until
someone runs `ufw enable` once. The module reads `ufw status`, the `INPUT`
policy and the nftables ruleset, and warns when the machine has services
listening beyond loopback and none of the three filters anything.

The probe runs as root and proves it: the serial console logs in as the desktop
user, because the application audit and every AT-SPI probe need that session,
so the module escalates with `biglinux->become_root` and reports the uid it
measured with. This is not a formality. The first run of this module measured
as the user and reported `sudoers NOPASSWD lines: 0` on a system whose
`/etc/sudoers` it could not open - `grep -s` hides the permission error - and
`ufw`, `iptables` and `nft` all came back empty for the same reason. The module
now refuses to report anything when it cannot reach uid 0.

Each item was true on a released ISO when this was written, which is exactly
why it starts as a warning: the job stays green, the numbers land in the report,
and a regression becomes visible on the next build. Turning one into a release
blocker is a single line in that module - replace `record_soft_failure` with
`die` - and should happen as each item is fixed.

## What a plan costs

Measured on this workstation (Ryzen, KVM, digest-pinned image) against
`biglinux_2026-08-19_k618`:

| | BIOS (`release`) | UEFI (`release_uefi`) |
| --- | --- | --- |
| Modules | 12 | 11 (no application audit) |
| Wall clock | 16-20 min | 14 min |
| Guest | 2 vCPUs, 4 GiB RAM, sparse 40 GiB disk | same, plus the OVMF pair |
| Installed system after the run | 5.9 GiB used of 40 GiB, 1.5 GiB RAM in use | same |
| Result artifacts | ~11 MiB per job | ~9 MiB per job |

Where the time goes on a BIOS plan: `installed_critical_apps` 9.8 min,
`installer_install` 4.6 min, `applications` 2.0 min, `live_desktop` 0.8 min,
`installed_brave` 0.8 min, and every remaining module under half a minute.
Two of the twelve modules are 75% of the run, which is where to look before
optimising anything.

## Running the gate day to day

- **One plan at a time on a workstation.** Each job uses 2 vCPUs, 4 GiB of
  guest RAM and a sparse 40 GiB disk. Running a plan next to
  `build-iso/build-local.sh` drove this machine into memory pressure twice.
- **Local runs**: `openqa/development/start-gate-local.sh` then
  `schedule-release-gate.sh`; see the development README.
- **Approval**: the same ISO has to pass BIOS and UEFI, and pass twice in a row
  without a code change before a build is called good. A single green run does
  not separate a fix from a flake.
- **When it goes red**, first ask which kind of failure it is. The gate names
  it: a module that dies with an AT-SPI tree in the message is a renamed or
  missing control (add the label); a module that dies on a timeout usually
  means the ISO really is broken.

## Rollback and maintenance

Use `publish_release=false` while investigating. Rollback is a normal Git
revert of the workflow or test commit on
`openqa-single-instance-experiment`; no server cleanup or credential rotation
is required because the production gate has no persistent openQA service or
openQA-specific secrets. Update the pinned image only after a known ISO passes
both firmware jobs and the static checks are green.
