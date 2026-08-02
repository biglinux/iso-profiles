# openQA development bridge

Owns the local, disposable openQA instance used by an AI agent to inspect jobs and
diagnostics through MCP while the release gate remains headless.

Hard invariants:

- MCP is enabled only with `mcp_enabled = read-only`.
- The endpoint binds to loopback and receives an ephemeral API credential.
- The development image is derived from the same digest-pinned openQA image used by
  the release workflow and adds the matching `openQA-mcp` package locally.
- The ISO is supplied by the caller; this bridge never builds one.

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

## Start the development instance

Use the exact ISO you want to investigate:

```bash
./openqa/development/start-mcp.sh \
  /path/to/biglinux_2026-07-31_k71.iso
```

The script checks `/dev/kvm`, validates the ISO filename, derives a local development
image from the pinned base, binds the Web UI and MCP only to `127.0.0.1`, starts a
disposable container, and prints a temporary Bearer credential. The MCP package is
installed at the exact openQA package version present in the base image. Copy that
credential into a local MCP client configuration based on
[`mcp.json.example`](mcp.json.example); do not commit the resulting file.

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
diagnostic context. Use `gh` or `openqa-cli` for scheduling, cloning, cancelling or
changing jobs, and keep those actions explicit in the work log.

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
