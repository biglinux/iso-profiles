# BigLinux openQA production gate

This document is the execution plan for making the BigLinux ISO gate usable in
continuous release work. It is deliberately separate from the production
README: the README describes the installed interface, while this document tracks
the evidence required before that interface may authorize publication.

## Layer A: operating contract

- **Owns:** the sequence from one built ISO candidate to a release decision,
  including persistent openQA, KVM workers, secure transfer, diagnostics, and
  rollback.
- **Hard invariants:** one immutable ISO is used by both firmware plans; the
  production path never starts an ephemeral openQA server and never accepts TCG;
  a failed, incomplete, skipped, or unverifiable mandatory job blocks release;
  build secrets are not exposed to the privileged ISO-build job.
- **Run:** after the external prerequisites are configured,
  `gh workflow run "Build ISO" --repo biglinux/iso-profiles --ref openqa-production-gate -f edition=kde -f kernel=lts -f manjaro_branch=stable -f big_branch=stable -f publish_release=false`.
- **Validate a change:** `git diff --check`, `bash -n openqa/production/*.sh openqa/development/*.sh`, `shellcheck -x openqa/production/*.sh openqa/development/*.sh`, `actionlint`, the repository Python tests, and a real BIOS+UEFI gate run.

---

## Why this plan exists

The release decision must answer two different questions:

1. Can this exact ISO boot, install, reboot, and authenticate in the supported
   firmware modes?
2. Which applications from the live image need attention, even when they are
   not release-blocking?

The first question belongs to the short mandatory gate. The second belongs to a
separate application audit that records every result and continues after an
individual failure. Mixing them makes a release depend on entries that may be
services, helpers, hidden launchers, or hardware-specific tools.

The production workflow therefore builds once, keeps the candidate private,
uploads it to a persistent openQA instance, schedules BIOS and UEFI in parallel,
collects evidence regardless of the result, and publishes only after the
mandatory gate succeeds.

```text
GitHub Actions                         Persistent openQA
----------------                       -----------------
build ISO once                         web UI + scheduler
  |                                    database + assets
  +-- checksum                         results + retention
  +-- private artifact                  worker: BIOS/KVM
  +-- restricted upload  ------------> worker: UEFI/KVM
  +-- schedule BIOS + UEFI
  +-- collect logs/video
  +-- gate decision
  +-- publish only on success
```

## Evidence status at the start of this plan

| Area | Current evidence | State |
| --- | --- | --- |
| Production workflow and scripts | Commit `e5e1a3a`; static checks pass | Verified locally |
| BIOS/UEFI plan split | `release` includes applications; `release_uefi` omits the broad application module | Verified in source |
| Secure receiver | Isolated contract tests pass | Verified locally |
| KVM capability on `192.168.1.48` | `/dev/kvm`, KVM modules, QEMU, OVMF, and NTP available | Host capability only |
| Persistent openQA on `192.168.1.48` | `openqa-cli` absent; web UI and scheduler inactive | Missing |
| GitHub production environment | No repository secrets or variables currently listed | Missing |
| Real BIOS job | No job from this branch | Missing |
| Real UEFI job | No job from this branch | Missing |
| Release decision | No green production gate and no controlled publication | Missing |

The previous experimental runs remain historical diagnostics only; they do not
prove this architecture.

## Phase 0 — freeze the test inputs

Before changing infrastructure:

1. Confirm the base branch and the exact production-gate commit.
2. Confirm the SHA-256 of the test code and needles.
3. Select the known-good ISO already used during bring-up. Do not rebuild it
   for every configuration attempt.
4. Record the ISO filename, byte count, SHA-256, kernel, firmware mode, and
   openQA build identifier.
5. Use the same ISO and digest for the BIOS and UEFI smoke run.
6. Only after the infrastructure smoke run passes, build one new candidate ISO
   and test that candidate once in both modes.

The patch, tarball, and checksum files named in the original request were not
present in the current workspace. If they are supplied later, verify their
checksum before applying them; do not silently substitute a different archive.

## Phase 1 — repository and workflow gate

Keep the production path limited to these responsibilities:

- consume the ISO artifact from the build job;
- verify MD5 and SHA-256;
- upload through the restricted receiver;
- validate the persistent server and worker capacity;
- schedule BIOS and UEFI concurrently;
- monitor both results;
- archive only the selected job results;
- generate the report and publish links in the Actions summary;
- return a failure that prevents the publish job from running.

The production path must not:

- run `openqa-bootstrap`;
- create a disposable database;
- launch a disposable web UI, scheduler, or worker;
- run the external smoke test as a redundant release gate;
- set `_GROUP_ID=0`;
- permit `QEMU_NO_KVM=1` or silently fall back to TCG;
- expose build credentials to the privileged container;
- use a mutable test branch or unpinned needles.

The development bridge may retain its local bootstrap helpers, but no production
workflow may invoke them. Any future change to the production scripts must
repeat the shell, YAML, Python, Perl, and secret-scanning checks before a real
run.

## Phase 2 — persistent openQA server

Configure a long-lived server, preferably separate from the GitHub runner and
from the ISO build host.

### Server requirements

- Install an official stable openQA/os-autoinst release, not an arbitrary source
  commit. Pin the deployment image or package repository revision used by the
  server and document the upgrade procedure.
- Run the web UI and scheduler as managed services.
- Use persistent PostgreSQL storage.
- Keep ISO assets and job results on persistent storage with known ownership.
- Configure retention and cleanup only after confirming that active jobs and
  their assets are excluded.
- Enable HTTPS and synchronize the clock with NTP.
- Create a BigLinux group and a CI-specific client identity.
- Restrict API and SSH access to the required GitHub runner path or relay.

### Server evidence

Record, without secrets:

```bash
openqa-cli --version
rpm -q openQA os-autoinst 2>/dev/null || true
systemctl status openqa-webui
systemctl status openqa-scheduler
df -h
```

Also record the persistent asset/result paths, free space, service logs, NTP
state, HTTPS certificate validation, and the group lookup through the openQA
API. A successful HTTP response alone is not proof that the scheduler or
workers are usable.

## Phase 3 — KVM worker pool

Create at least two usable worker slots. They may initially be on one capable
host only if two independent workers can run concurrently without resource
starvation; separate hosts are preferred for fault isolation.

For every worker, verify:

```bash
test -c /dev/kvm
test -r /dev/kvm
test -w /dev/kvm
lsmod | grep '^kvm'
```

The openQA worker properties must show:

- connected and healthy;
- class `biglinux-kvm`;
- QEMU backend;
- access to `/dev/kvm`;
- no TCG fallback;
- enough RAM, CPU, and disk;
- OVMF firmware for UEFI.

Run one controlled diagnostic job and preserve its autoinst log, worker log,
and QEMU command line. Acceptance requires `-enable-kvm` and rejection of
TCG markers. Merely finding the device node is insufficient.

## Phase 4 — secure ISO receiver

Install `receive-iso.sh` as a root-owned executable behind a fixed wrapper
that exports the production ISO directory. The authorized key should specify
the forced command, disable PTY and forwarding, and use a non-login account. Do
not allow the client to select the destination through an inherited environment
variable.

Run all negative receiver tests in an isolated temporary directory. The matrix
must cover:

1. valid upload;
2. wrong SHA-256;
3. declared size smaller than the stream;
4. declared size larger than the stream;
5. interrupted transfer;
6. extra bytes;
7. `../` filename;
8. absolute or slash-containing filename;
9. empty filename;
10. non-ISO extension;
11. arbitrary SSH command;
12. identical repeated upload;
13. simultaneous uploads;
14. configured disk-size limit.

For each case preserve exit status, expected/observed result, created files,
and temporary-file state. Never run destructive failure tests against the live
openQA asset directory.

## Phase 5 — GitHub environment and workflow wiring

Create the protected `openqa-production` environment with these secrets:

- `OPENQA_SSH_PRIVATE_KEY`;
- `OPENQA_KNOWN_HOSTS`;
- `OPENQA_TEST_PASSWORD`.

Create these non-secret variables:

- `OPENQA_URL`;
- `OPENQA_SSH_HOST`;
- `OPENQA_SSH_USER`;
- `OPENQA_SSH_PORT`;
- `OPENQA_GROUP`;
- `OPENQA_WORKER_CLASS`;
- `OPENQA_REMOTE_ISO_DIR`.

Check that the build job cannot read the production secrets. The reusable gate
must receive secrets explicitly, use strict host-key checking, and remove
temporary files in an `always()` cleanup step.

Use unique `BUILD` and ISO names per candidate. A cancelled run must not delete
assets still referenced by another build.

## Phase 6 — test architecture and real smoke run

Use `openqa/main.pm` as the schedule owner. Keep these plans distinct:

- BIOS release plan: boot, live desktop, critical applications, Calamares,
  installation, reboot, login, health, and Brave.
- UEFI release plan: boot, live basics, Calamares, installation, reboot, login,
  health, and Brave.
- application audit plan: recursive `.desktop` discovery and per-entry report,
  executed manually or on a schedule and not release-blocking.

The application audit must launch programs directly, use AT-SPI to prove that a
usable accessible object/window appeared, perform a small supported interaction,
close the program cleanly, record exit status and memory, and continue after
failure. Screenshots are only a black-screen sanity check.

The Calamares path must verify each page transition, selected destructive
partition mode, user creation, installation completion, ISO ejection, reboot,
boot from disk, login, and post-install health. A “completed” screen alone is
not evidence of a valid installation.

## Phase 7 — evidence and failure handling

Every run must preserve, including failed runs:

- BIOS and UEFI job URLs and IDs;
- module results;
- screenshots and openQA video;
- autoinst logs;
- worker and QEMU diagnostics;
- Calamares logs when available;
- HTML report;
- ISO filename and SHA-256;
- timestamps for each phase.

Collection must never replace the original test failure with success. If
collection itself fails, the workflow remains failed and reports that failure.
Artifacts must be uniquely named by build and run ID and must not contain
secrets.

## Phase 8 — negative, concurrency, and publication validation

Run controlled failures for invalid endpoint, invalid credentials, offline
worker, missing KVM, bad ISO, invalid SHA, invalid scenario, invalid Perl,
missing needle, BIOS failure, UEFI failure, install timeout, cancellation,
report failure, collection failure, artifact failure, and publication after a
red gate.

For every negative case, prove:

- the correct step fails;
- the workflow is red;
- no release or tag is published;
- diagnostics survive;
- secrets are absent from logs;
- invalid assets are not promoted.

Then run two different build identifiers concurrently and prove that their ISO,
jobs, results, and cancellation behavior remain isolated.

## Phase 9 — performance, release, and handoff

Measure the old and new workflows using timestamps rather than estimates:

- build completion to upload start;
- upload duration;
- upload completion to first job;
- BIOS duration;
- UEFI duration;
- total duration;
- worker CPU/RAM/disk;
- artifact sizes;
- collection duration.

Run the final candidate once with `publish_release=false`. After BIOS and UEFI
pass and all evidence is reviewed, run the controlled green case with
`publish_release=true`. Recompute checksums after downloading and recombining
published assets.

The PR can leave draft status only when all mandatory acceptance rows have real
job evidence. Local tests, a known-good ISO, or a simulated KVM command cannot
substitute for the real BIOS and UEFI jobs.

## Rollback

1. Disable publication by running with `publish_release=false`.
2. Stop accepting new candidates if the persistent server or workers are
   unhealthy.
3. Preserve active assets and job results.
4. Revert the production workflow commit through a normal reviewed Git revert;
   do not rewrite history.
5. Keep the last known-good ISO and its checksum available.
6. Re-enable publication only after the server, worker, and gate checks pass
   again.

## Retrieval questions

- Which evidence proves that a job used KVM rather than TCG? See **Phase 3**.
- Which check prevents an incomplete ISO from reaching the asset directory? See
  **Phase 4**.
- Why are all `.desktop` entries outside the mandatory gate? See the opening
  problem statement and **Phase 6**.
- What must be true before the PR stops being draft? See **Phase 9**.
