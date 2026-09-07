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

## Finding the name of a control

The tests drive the desktop through accessibility, so the thing to know when a
module fails is the *name* AT-SPI publishes for a control, not where it is on
screen. The gate hands that over on failure: `activate_widget` dies with the
whole observed tree, for example

```
no showing and sensitive control for push button|button matching
['Done', 'Concluir', 'Finish', 'Finalizar']; matching roles observed:
button/Voltar (insensitive); button/Próximo; button/Concluído
```

which names the fix - add `Concluído` to the list in `openqa/lib/calamares.pm`.
Labels are compared with markup, case, punctuation and accents folded away
(`data/atspi_probe.py`), so a missing accent is never the problem; a different
word always is.

For an interactive look at the tree, start the MCP bridge and ask openQA for a
running job, or run the probe by hand in the guest:

```bash
python3 /tmp/openqa-atspi-probe.py inventory --state /tmp/openqa-atspi-state.json --timeout 30
```

## Run a release plan on this machine

`start-mcp.sh` exists to look at results. To *run* a plan the container needs
what the workflow gives it — the test password, the worker class the job asks
for, a results directory the host can read, and the OVMF pair for UEFI — so use
the gate wrapper instead:

```bash
./openqa/development/start-gate-local.sh /path/to/biglinux.iso            # BIOS
./openqa/development/start-gate-local.sh --firmware uefi /path/to/iso     # UEFI

source ~/.cache/biglinux-openqa-gate/gate-env.sh
./openqa/development/schedule-release-gate.sh --firmware bios
./openqa/development/schedule-release-gate.sh --applications-shard 0 4

docker rm -f biglinux-openqa-gate
```

The wrapper writes `gate-env.sh` with every variable
`schedule-release-gate.sh` requires, including the ISO checksum it refuses to
run without. It waits until the API, the scheduler **and** a worker carrying
`biglinux-kvm` are up: a worker without that class leaves the job scheduled
until the five-hour monitor timeout, with nothing on screen to explain it.

Resource limits worth respecting on a workstation:

- one plan at a time uses 2 vCPUs, 4 GiB of guest RAM and a sparse 40 GiB disk;
- **do not run a plan while `build-iso/build-local.sh` is building an ISO** —
  the two together drove this machine into memory pressure;
- remove the container between plans (`docker rm -f`), or the next
  `start-gate-local.sh` refuses to start on the existing name.

The container copies the read-only `/workspace-source` mount to `/workspace`
once, at startup. Editing the tests between two plans on the **same** container
therefore changes nothing, and a deleted file is worse than an unchanged one:
`cp -a` never removes it, so a needle you just dropped keeps matching. Re-sync
before scheduling again, or restart the container:

```bash
docker exec biglinux-openqa-gate \
  rsync -a --delete --chown=_openqa-worker:_openqa-worker /workspace-source/ /workspace/
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
