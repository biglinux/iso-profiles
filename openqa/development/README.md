# openQA development bridge

Owns the local, disposable openQA instance used by an AI agent to inspect jobs and
diagnostics through MCP while the release gate remains headless.

Hard invariants:

- MCP is enabled only with `mcp_enabled = read-only`.
- The endpoint binds to loopback and receives an ephemeral API credential.
- The development image is derived from the same digest-pinned openQA image used by
  the release workflow and adds the matching `openQA-mcp` package locally.
- The ISO is supplied by the caller; this bridge never builds one.
- The GitHub gate creates one disposable openQA instance and one KVM worker in each
  BIOS and UEFI runner. It rejects a run whose job archive does not prove KVM. This
  bridge uses the same pinned image and test sources for local investigation.

Run: `./openqa/development/start-mcp.sh /absolute/path/to/biglinux.iso`

Validate: `bash -n openqa/development/start-mcp.sh && shellcheck openqa/development/start-mcp.sh`

---

## Why this exists

The release workflow must be predictable and non-interactive. During development, an
agent still needs to inspect a failed screen, compare jobs, and read artifacts without
receiving permission to change or trigger jobs through the same interface. This bridge
keeps those concerns separate:

```text
same pinned image + same ISO
          |
          +--> local openQA Web UI + read-only MCP --> agent observes and explains
          |
          +--> gh/openqa-cli -----------------------> human-approved actions
          |
          +--> GitHub release workflow --------------> automatic headless gate
```

The openQA MCP implementation is experimental and read-only. The official
documentation describes the `/mcp` endpoint and Bearer authentication; this bridge
uses the same contract. It does not replace the repository's pinned `CASEDIR`, needle
or workflow settings.

## Canonical daily test configuration

[`release-gate.yaml`](release-gate.yaml) is the source of truth for the mandatory
firmware plans and four application shards. The module sequence for each schedule
remains owned by [`../main.pm`](../main.pm), and the application policy is owned by
[`../application-policy.yaml`](../application-policy.yaml).

The development scheduler consumes this manifest locally:

```bash
BIGLINUX_OPENQA_VERSION=candidate \
BIGLINUX_OPENQA_BUILD=dev-2026-07-31-k71 \
BIGLINUX_ISO_FILENAME=biglinux_2026-07-31_k71.iso \
./openqa/development/schedule-release-gate.sh --dry-run

BIGLINUX_OPENQA_VERSION=candidate \
BIGLINUX_OPENQA_BUILD=dev-2026-07-31-k71 \
BIGLINUX_ISO_FILENAME=biglinux_2026-07-31_k71.iso \
./openqa/development/schedule-release-gate.sh --dry-run --applications-shard 0 4
```

The GitHub workflow uses the same manifest through an ephemeral local instance, while
a local run can use the already-started development container and the existing ISO:

```bash
printf '%s' 'temporary-password' > /path/to/test-password
BIGLINUX_OPENQA_CONTAINER=biglinux-openqa-dev \
BIGLINUX_OPENQA_VERSION=candidate \
BIGLINUX_OPENQA_BUILD=dev-2026-07-31-k71 \
BIGLINUX_ISO_FILENAME=biglinux_2026-07-31_k71.iso \
BIGLINUX_TEST_PASSWORD_FILE=/path/to/test-password \
BIGLINUX_OPENQA_DIAGNOSTICS_DIR=/path/to/diagnostics \
./openqa/development/schedule-release-gate.sh --firmware bios
```

Changing the daily matrix therefore means reviewing `release-gate.yaml`; changing
what a plan does means reviewing the corresponding schedule in `main.pm`. No ISO
generation or manual test-list duplication is part of this path.

## Application validation

Each `applications` shard discovers every `Type=Application` desktop entry below
`/usr/share/applications/`, recursively. It launches each entry through
`data/desktop_entry_launcher.py`, so the Desktop Entry is parsed without concatenating
its `Exec` value into a shell command. Hidden, non-application, and otherwise
non-launchable entries remain in `application-metrics.json` with a reason instead of
silently disappearing. `NoDisplay=true` does not exclude an application: it is still
launched and validated.

The contract is intentionally small: start the Desktop Entry, confirm that a new
AT-SPI window exists, and record the process memory. If AT-SPI cannot expose the
window, a PID-scoped X11 window is enough; terminal and daemon entries use the
supervisor child as their process-start evidence. No menu action, screenshot, title
allowlist, or application-specific close path is required. All graphical entries use
deterministic software rendering (`llvmpipe`, with Qt Quick's software backend) and
the X11 Qt/GDK backends.
After every case, windows and process trees created after the session baseline are
closed or terminated so a broken application cannot contaminate the next case. Probe
calls have an external deadline as well as their open deadline, so a stalled
accessibility provider becomes a reportable application failure instead of blocking
the whole suite. The module fails only after the inventory is exhausted. The optional
`BIGLINUX_APPLICATION_TIMEOUT` variable controls the per-entry launch timeout and
defaults to 8 seconds.

The per-entry JSON records peak RSS, peak PSS, and peak process count for the process
tree. Four jobs use `sha256(relative_desktop_id) modulo 4`; the aggregator requires
their union to equal the launchable inventory exactly. The HTML report renders
those values alongside the open result.
Screenshots are not application assertions. The normal openQA video remains the video
artifact for the job and is collected with the other openQA diagnostics.

## Start the development instance

Use the exact ISO you want to investigate:

```bash
./openqa/development/start-mcp.sh \
  /path/to/biglinux_2026-07-31_k71.iso
```

The script checks `/dev/kvm`, rejects an active VirtualBox VM/process, validates the
ISO filename, derives a local development image from the pinned base, binds the Web UI
and MCP only to `127.0.0.1`, starts a disposable container, and prints a temporary
Bearer credential. The MCP package is installed at the exact openQA package version
present in the base image. Copy that credential into a local MCP client configuration based on
[`mcp.json.example`](mcp.json.example); do not commit the resulting file.

This bridge intentionally uses the same QEMU backend as the production configuration,
but the local bridge requires KVM for a practical interactive development cycle. It
must not be started while a VirtualBox VM is running because both hypervisors compete
for the host virtualization extension. The production gate never falls back to TCG:
the worker class and archived QEMU command must prove KVM. Neither path requires
virgl; the `mpv` application test always selects software rendering. The local
VirtualBox host remains available for unrelated development VMs when the bridge is
stopped.

The Docker port proxy appears as a non-local request inside the container. The bridge
therefore marks only `/mcp` as the secure local proxy hop required by openQA's token
validation; the container itself is still published only on host loopback.

The repository is mounted read-only by default. If the openQA needle editor is being
used to write a reviewed development change, opt in explicitly:

```bash
./openqa/development/start-mcp.sh --write-repo /path/to/biglinux.iso
```

Stop the instance when finished:

```bash
docker stop biglinux-openqa-dev
```

## How the agent uses it

MCP is for read-only investigation: job settings, module results, screenshots and
diagnostic context. The shared scheduler uses `openqa-cli` for the explicit write
operation of creating the daily jobs; use `gh` for the GitHub workflow and release
actions.

The mounted repository is available inside the container as `/workspace`. A
development job can point `CASEDIR` at that path, or it can use a reviewed Git ref just
like the release workflow. The ISO remains an existing asset mounted read-only under
openQA's factory directory.

After a fix, run the normal workflow with the candidate artifact. A green development
job is useful evidence, but it does not replace the BIOS+UEFI release gate.

## Security boundaries

The MCP endpoint is not published outside the host. The credential is generated for
the disposable local database and is printed only so the local client can connect. The
release workflow does not mount this configuration, expose MCP, or grant the agent a
write-capable openQA API.

The first start may download the signed `openQA-mcp` package from the openSUSE
repositories while building the local development layer. The resulting image is
cached by the pinned base digest; the release workflow never uses this layer.
