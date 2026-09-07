# BigLinux ephemeral openQA implementation plan

This document records the production contract and the evidence still required
for a real GitHub-hosted run. It does not describe a persistent server.

## Contract

- `build-iso.yml` builds once and stores the ISO plus checksums as a private
  artifact.
- The reusable workflow fans out to independent `bios`, `uefi`, and four
  application-shard jobs on `ubuntu-24.04`.
- Each job validates `/dev/kvm`, prepares OVMF when needed, starts the pinned
  openQA single-instance image, and starts one worker with class
  `biglinux-kvm`.
- The local API schedules one plan per runner. BIOS uses `release`, UEFI uses
  `release_uefi`, and the four application runners use deterministic shards of
  the complete recursive desktop-entry inventory.
- Diagnostic collection runs after failures. The aggregator requires all four
  application payloads and publication depends on the firmware and application
  gates being successful.

## Architecture

```text
Build artifact
   |
   +-- BIOS runner -> local openQA -> local worker -> /dev/kvm -> release_bios
   |
   +-- UEFI runner -> local openQA -> local worker -> /dev/kvm + OVMF -> release_uefi
   +-- 4 app runners -> local openQA -> local worker -> /dev/kvm -> applications 0..3
   +-- aggregator -> complete inventory and result gate
```

The runners do not contact an openQA server. SSH, external API credentials,
external workers, persistent assets, and self-hosted infrastructure are outside
this implementation.

## Source of truth

- `openqa/openqa-image.txt` pins the openQA image by tag and digest.
- `openqa/scenario-definitions.yaml` owns machines and firmware settings.
- `openqa/development/release-gate.yaml` owns the firmware plans and four-shard matrix.
- `openqa/application-policy.yaml` owns explicit exclusions, aliases, and critical apps.
- `openqa/main.pm` owns the module sequence.
- `.github/workflows/openqa-single-instance-experiment.yml` owns runner
  lifecycle, artifact transfer, KVM checks, diagnostics, and the gate.

## Required evidence

### Local evidence recorded on 2026-09-07

A full `release` plan (BIOS) passed on this hardware against
`biglinux_2026-08-19_k618.iso`, all eleven modules green: live desktop,
application audit, installer launch, partitions, users, installation, installed
boot, login, health, critical applications and Brave. Local job id 10, run in
the disposable container started by `openqa/development/start-gate-local.sh`
with KVM and the digest-pinned image.

Job 18 is the one that matters: twelve modules, eleven passed, and
`installed_security` softfailed as designed with eight measured items, taken by
a probe that proved it was running as uid 0. Every item reproduces a finding
from the manual audit of the same ISO:

| Measured | Value on job 18 |
| --- | --- |
| effective `NOPASSWD` grants | 2 (`Xbig`, `biglinux-backlight-restore`) |
| services listening beyond loopback | 8 (`smbd` 139/445, Avahi 5353, `kdeconnectd` 1716) |
| effective firewall filtering | none: `ufw` unit enabled, `ufw status` inactive, `INPUT` policy `ACCEPT` |
| unsigned repository databases | `SigLevel = Required DatabaseNever` |
| plain-HTTP mirrors | 1 |
| `kptr_restrict` / `dmesg_restrict` | 0 / 0 |
| AppArmor with `audit=0` | enforcing, denials discarded |
| pending updates on a fresh install | 200 |

It took five runs to get numbers worth reading, and every correction was to the
measurement rather than to the ISO:

- it first asked `systemctl is-enabled`, which answers `enabled` on every
  install because `ufw` is in `enable_systemd`, while the machine still
  forwards every packet. It now reads `ufw status`, the `INPUT` policy and the
  nftables ruleset, and reports whether anything filters.
- the whole probe then ran **as the desktop user**. The console was named
  `root-virtio-terminal` but `biglinux.pm` logs in as `biglinux`, and the
  forced `PS1='# '` completed the illusion. Unprivileged, `grep -s NOPASSWD
  /etc/sudoers` hides its permission error and returns 0, and `ufw`,
  `iptables` and `nft` all return nothing - a system that could not be read
  was reported as clean. The console is now named `user-virtio-terminal`, the
  module escalates through `biglinux->become_root`, and it refuses to report
  any root-only item unless the probe answers uid 0.

- and the `NOPASSWD` count included the commented `%wheel ALL=(ALL:ALL)
  NOPASSWD: ALL` example that ships in `/etc/sudoers`, reporting three grants
  on a system that has two.

`luks=none` is correct rather than unmeasured: this plan installs an
unencrypted disk.

Making the probe privileged exposed two credential leaks, both fixed here:

| Leak | Cause | Fix |
| --- | --- | --- |
| the test password appeared in the uploaded serial log | `become_root` typed it as soon as it issued `sudo`, so the bytes reached the tty before sudo started reading and the line discipline echoed them - sudo then read the *next* typed line as the password and failed | wait for sudo's own prompt, built through `printf` so the command echo cannot match it, and type nothing when it never appears |
| the test password sat in `scheduled-product-*.json` | openQA hides `_SECRET_*` in its web UI but returns it verbatim from the scheduled-product API, and the diagnostics directory is uploaded as a job artifact | `schedule-release-gate.sh` redacts every `_SECRET_*` value before the file is kept |

A failed escalation also has to leave the console usable: sudo keeps asking
after a wrong password and swallows whatever is typed next, which is why job 17
lost `installed_critical_apps` to an unrelated AT-SPI timeout.

Getting there required six defects to be fixed, all of them in the gate rather
than in the ISO, and worth listing because they show what this evidence is
actually worth:

| Defect | Effect while it lasted |
| --- | --- |
| `calamares.pm` had non-ASCII literals without `use utf8` | the probe was asked for a button named `Pr\udcf3ximo`; the installer could never advance in Portuguese |
| `@DONE` was missing "Concluído" | the installation finished and the module still failed |
| serial login expected `Password:`, the installed system asks `Senha:` | a perfectly installed system looked like a boot failure |
| five needles from 2026-08-04 no longer matched | one of them clicked "English, United States" instead of Portuguese |
| `build-local.sh` preferred rootless podman | no ISO could be built locally at all |
| `build-local.sh` did not mount the chroot work directories | the build died on overlayfs after downloading every package |

### The approval criterion, met locally

The gate is called good when the same ISO passes both firmware plans twice in a
row without a code change between the runs. That happened on 2026-09-07 with
`biglinux_2026-08-19_k618`:

| Job | Plan | Modules | Result |
| --- | --- | --- | --- |
| 2 | `release_uefi` | 11 | every module passed, `installed_security` softfailed by design |
| 3 | `release_uefi` | 11 | identical |
| 4 | `release_bios` | 12 | identical |
| 5 | `release_bios` | 12 | identical |

Jobs 2/3 and 4/5 are consecutive runs of the same checkout. The UEFI runs also
close the firmware evidence that was previously untested locally: the installed
system reports `efi=1`, `/boot/efi` mounted, and `efibootmgr` listing a
`BootCurrent` entry.

The UEFI plan had never run on this machine, and the first attempt failed
before booting: `qemu-img: Could not open '/run/ovmf/OVMF_CODE.fd': Permission
denied`. `start-gate-local.sh` creates its state directory under `umask 077`
and chmods only `results`, so the container could not traverse the OVMF
directory as `_openqa-worker`; the variable store also has to be writable by
that user rather than by the invoking one.

### First cross-build comparison

`build-iso/build-local.sh` produced `biglinux_2026-09-07_k618.iso` (5.1 GiB, 13
minutes with `-r https://linorg.usp.br/manjaro`), and a BIOS plan against it
passed all twelve modules with `installed_security` softfailed. Comparing its
posture with the released `2026-08-19` ISO is what this module exists for:

| Measured | 2026-08-19 | 2026-09-07 |
| --- | --- | --- |
| effective `NOPASSWD` grants | 2 | 2 |
| listening beyond loopback | 8 (`smbd`, Avahi, `kdeconnectd`) | 6 or 8, see below |
| firewall filtering | none | none |
| `audit=` on the kernel command line | `audit=0` | absent |
| pending updates on a fresh install | 200 | 295 |

The `audit=` row also exposed a measurement bug: `grep ... | head -1 || echo
unset` never reports "unset", because the pipeline's exit status is `head`'s.
An absent setting printed an empty value that read like a measurement. With
that fixed, the 2026-09-07 ISO reports `audit=unset`, so the AppArmor warning
correctly stops firing.

The listening count is the one item that moves between runs of the same ISO: it
was 6 on one run and 8 on the next, because `kdeconnectd` binds its two
sockets when the desktop session gets there, which is sometimes after the
probe. The port list in the uploaded log is the part to read; the count is a
trend, not a constant.

The build itself needed two more fixes, both found the hard way:

- `build-local.sh` kept its chroots in `./output/.buildiso-work`, inside the
  checkout the gate mounts. `start-container.sh` copied that with `cp -a`, hit
  the device nodes in the unpacked root filesystems, and the container died
  before the web UI answered. The work directory now defaults to
  `${XDG_CACHE_HOME:-$HOME/.cache}/biglinux-build-iso`, and the container copy
  is an `rsync` that excludes `./output` and `.git`.
- the Manjaro mirror flag takes a base URL, not a pacman template: passing
  `.../$repo/$arch` is rejected, and a mirror that answers on its front page
  can still 404 every database.

### Why every GitHub run failed, and it was not the tests

The last three `Build ISO` runs on this branch failed in August, and reading
their job steps through the public API shows every openQA job dying at the same
place: step 4, **"Validate pinned openQA image"**. Not a test, not the ISO -
the pin itself:

```
registry.opensuse.org/.../openqa-single-instance:5.1784641659.4.14.164@sha256:c8ac19...
```

Both the digest and the tag now answer `404`. The openSUSE devel registry keeps
five tags for this image and rotates them, so the pin this repository trusted
has been garbage-collected upstream. Local runs never noticed because the image
was already in the workstation's Docker cache - which is exactly how a dead pin
survives unnoticed until a CI runner has to pull it.

The pin is now `5.1788175640.07173.14.211@sha256:3dd009...` (openQA
5.1788175640.07173bb1, os-autoinst 5.1787772129.e7dc5f2), and it was raised the
way the production README demands rather than as a routine bump: a full BIOS
plan and a full UEFI plan against `biglinux_2026-08-19_k618`, both green with
`installed_security` softfailed. The experimental
`SCENARIO_DEFINITIONS_YAML` schema did not move, so
`openqa/scenario-definitions.yaml` needed no change.

Because the registry keeps only five tags, this will happen again. The pin has
to be raised on a schedule rather than when a release run discovers it, and the
digest is worth checking before every dispatch:

```bash
curl -sI -H 'Accept: application/vnd.oci.image.index.v1+json' \
  "https://registry.opensuse.org/v2/devel/openqa/containers/opensuse/openqa-single-instance/manifests/$(cut -d: -f2 <openqa/openqa-image.txt | cut -d@ -f1)" \
  | head -1
```

`start-gate-local.sh` also could not prepare UEFI twice: it copied the firmware
over the read-only file the previous run left, and failed with `Permissão
negada` before the plan started. It uses `install` now.

### What the first real GitHub runs found

Two dispatches on this branch, and each one found a defect that no local run
could have found:

| Run | Where it stopped | Cause |
| --- | --- | --- |
| 34119636509 | every openQA job, immediately | `isotovideo died: Failed to check out <sha> in '/workspace'` - the workspace copy excluded `.git`, and the production gate pins `TEST_GIT_REFSPEC` to the run's commit and checks it out inside `CASEDIR`. A local plan pins no refspec. |
| 34123679945 | `live_desktop`, application shards | the language filter was typed at the default speed and the runner dropped a keystroke: the search box read `Bazil`, nothing matched, and `Return` activated nothing |

Both runs did confirm the parts that used to fail: the ISO built, "Validate
pinned openQA image" passed with the new pin, "Validate repository sources"
passed with the three new guards, KVM was proved, and the uploaded
`scheduled-product-*.json` carries `_SECRET_BIGLINUX_TEST_PASSWORD:
"[redacted]"`.

The typing fix is worth reading as a pattern rather than a tweak: without an
accessibility tree, a keyboard-driven page needs a step whose success is
observable. Typing the filter and pressing `Return` is not observable; pressing
`Return` **and the screen changing** is. So the language step now clears the
box, types slowly (`max_interval => 20`), waits for the debounced filter, and
retries up to three times, treating "the screen did not change" as "the filter
matched nothing".

Run 34130169469 got every module to run and exposed four more defects, none of
which a local plan could have shown:

| Defect | Why local runs never saw it |
| --- | --- |
| the gate rejected `softfailed`, so a plan in which every module passed still failed the job | `installed_security` softfails by design; the scheduler only accepted `passed`, which made Phase E and the gate contradict each other |
| `become_root` typed the uid check before sudo had exited, and sudo read it as another password attempt | the local shell is fast enough that sudo had always returned first |
| the failed-escalation cleanup used `send_key 'ctrl-c'`, which kills the virtio backend (`Virtio terminal ... do not support send_key`) | escalation never failed locally, so the cleanup path never ran |
| `copy-job-results.sh` deleted the archived error-page screenshots from the runner, but openQA writes them as root | that script only runs in the workflow |

And one that a local run did reproduce once it was written: the process-exit
wait was an unbounded `while` loop with a 15-second serial budget. When an
application took longer to close, the loop kept running in the guest's
foreground and read the next typed command instead of the shell, so one slow
close cascaded into three failed modules. It is now bounded in the guest by its
own deadline - with `break` and a status variable rather than `exit`, because
`_run_guest_command` runs the command in the login shell and an `exit` there
closes the console for every module that follows.

The remaining work for the GitHub side is unchanged:

Before calling the implementation ready, record a successful GitHub Actions run
with both firmware jobs and all four application shards. The artifacts must show:

| Area | Evidence |
| --- | --- |
| KVM | `/dev/kvm`, `kvm-ok`, QEMU smoke test, and archived KVM command |
| BIOS | one local job ID, passed modules, installation and installed boot |
| UEFI | one local job ID, deterministic non-Secure-Boot OVMF pair, EFI checks, and passed modules |
| Applications | four shard IDs, complete inventory coverage, memory metrics, and no failures |
| Diagnostics | archive, `autoinst-log.txt`, screenshots, video when produced, report |
| Gate | red BIOS/UEFI blocks publication; green pair permits controlled publication |
| Isolation | two runs keep artifacts and local containers separate |
| Performance | measured build, download, startup, BIOS, UEFI, collection, total times |

Static validation is necessary but not sufficient:

```bash
git diff --check
bash -n openqa/production/*.sh openqa/development/*.sh data/*.sh
shellcheck -x openqa/production/*.sh openqa/development/*.sh data/*.sh
actionlint
python3 -m unittest discover -s data -p 'test_*.py'
python3 -m unittest discover -s openqa/data -p 'test_*.py'
python3 -m unittest discover -s openqa/report -p 'test_*.py'
(cd build-iso && python3 -m pytest tests -q)
```

The workflow's "Validate repository sources" step adds three checks that no
local command covers: every non-ASCII Perl module declares `use utf8`, no needle
file or tag is left without the other side, and no new `assert_screen`,
`assert_and_click` or `check_screen` appears outside the two modules allowed to
use pixels.

Run these commands from the checked-out branch. A missing dependency is a
validation limitation, not a pass.

## Negative cases

Use disposable workflow inputs or local fixtures for `/dev/kvm` absence,
permission denial, missing OVMF, invalid ISO/checksum, invalid scenario, TCG
evidence, absent KVM evidence, worker/API/scheduler startup failure, BIOS or
UEFI failure, timeout, cancellation, result collection failure, artifact
failure, and publication after a red gate. Each case must remain red, retain
diagnostics when possible, and create no release or public asset.

## Rollback

Run with `publish_release=false`, revert the offending commit normally, and
rerun the known ISO in BIOS and UEFI. Do not reuse a stale result or publish an
ISO that was not tested by the same build artifact.
