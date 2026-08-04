# BigLinux openQA release gate

Owns the release-blocking openQA path from the private ISO artifact to the
publication decision.

Hard invariants:

- BIOS and UEFI run in independent `ubuntu-24.04` jobs.
- Each job starts one local openQA single-instance container and one local KVM worker.
- `/dev/kvm` and the archived QEMU command must prove KVM; TCG is never accepted.
- The ISO is verified from the build artifact or an existing release before use.
- A failed, cancelled, incomplete, or unverifiable mandatory job blocks publication.
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
modes. The gate also runs the selected critical applications only in BIOS. The
recursive `.desktop` audit remains the separate `applications` schedule and is
not a release prerequisite.

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
   |
   +-- publish only when build, BIOS, and UEFI are successful
```

The container image is the digest-pinned value in
[`../openqa-image.txt`](../openqa-image.txt). It is the official openQA
single-instance image used by the local development bridge. The container is
stopped and removed at the end of every job; its database, assets, and results
are not reused by another run.

## Inputs and artifacts

The reusable workflow receives `candidate_artifact`, `iso_filename`, `version`,
and `build_id` from `build-iso.yml`. The manual dispatch path downloads either
the direct release ISO or every numbered `.7z.*` part, verifies the complete
sequence, extracts the ISO, and checks both checksum files.

The build publishes no public asset before the gate. The same artifact is
downloaded by both firmware jobs, so BIOS and UEFI test the same bytes.

Every firmware job uploads a uniquely named diagnostic artifact containing the
ISO identity, resource measurements, container logs and metadata, job IDs,
openQA archives, module details, screenshots, video when generated, KVM
evidence, and the HTML report. Collection runs after failures and never changes
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
non-dry invocation requires `--firmware bios` or `--firmware uefi`, submits
`SCENARIO_DEFINITIONS_YAML` through the official local `openqa-cli` API, and
polls the returned product and job JSON. It never uses SSH, a remote API key,
or a server URL.

The checked-out sources are mounted read-only at `/workspace-source`; the
container entrypoint copies them to writable `/workspace` before openQA checks
out the pinned `TEST_GIT_REFSPEC`. The job records the full `GITHUB_SHA`, uses
the copied scenario file and needles, and sets `QEMU_NO_KVM=0`. BIOS uses the
`release` schedule with the explicit critical application filter. UEFI uses
`release_uefi`, which does not load the broad application audit.

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
and keeps its report separate from the release gate. Screenshots are not
application assertions; the normal openQA video remains the visual evidence.

## Manual local investigation

For an interactive investigation, start the disposable MCP bridge with an
existing ISO:

```bash
./openqa/development/start-mcp.sh /absolute/path/to/biglinux.iso
```

This is local development only. It uses the same pinned image, requires KVM,
binds its endpoint to loopback, and is not a second production implementation.

## Rollback and maintenance

Use `publish_release=false` while investigating. Rollback is a normal Git
revert of the workflow or test commit on
`openqa-single-instance-experiment`; no server cleanup or credential rotation
is required because the production gate has no persistent openQA service or
openQA-specific secrets. Update the pinned image only after a known ISO passes
both firmware jobs and the static checks are green.
