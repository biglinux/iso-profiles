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
```

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
