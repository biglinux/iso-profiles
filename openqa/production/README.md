# BigLinux production openQA gate

The production workflow does not start openQA in GitHub Actions. It uploads the
candidate ISO through an upload-only SSH key, uses the authenticated openQA
HTTPS API for validation and job control, and collects the two job archives after
the BIOS and UEFI plans finish.

## Persistent openQA host

Install and maintain official stable distribution packages for:

```text
openQA
openQA-client
os-autoinst
QEMU
OVMF
```

Keep these services and paths persistent:

```text
openqa-webui
openqa-scheduler
/var/lib/openqa/share/factory/iso
/var/lib/openqa/testresults
/var/lib/openqa/pool
```

The host must provide HTTPS with a trusted certificate, synchronized time, a
BigLinux job group, and at least two connected workers in the `biglinux-kvm`
class. Each worker must have read/write access to `/dev/kvm`, sufficient RAM and
CPU, persistent result storage, and OVMF firmware. A job log must prove KVM;
`QEMU_NO_KVM=0` is not evidence by itself.

The server-side operational checklist remains responsible for service state,
PostgreSQL, retention, asset cleanup, disk capacity, NTP, and worker health.
Those privileged checks are not executed through a general-purpose SSH shell
from GitHub Actions.

## GitHub configuration

Create the protected environment `openqa-production` with only these secrets:

```text
OPENQA_API_KEY
OPENQA_API_SECRET
OPENQA_SSH_PRIVATE_KEY
OPENQA_KNOWN_HOSTS
OPENQA_TEST_PASSWORD
```

The API key belongs to an operator account dedicated to CI. It is passed to the
pinned official openQA client container through environment variables and is
never placed in command-line arguments.

Add these non-secret variables:

```text
OPENQA_URL
OPENQA_SSH_HOST
OPENQA_SSH_USER
OPENQA_SSH_PORT
OPENQA_GROUP
OPENQA_WORKER_CLASS
OPENQA_REMOTE_ISO_DIR
```

`OPENQA_REMOTE_ISO_DIR` configures the fixed destination exported by the
server-side forced-command wrapper. The GitHub job does not use it to execute
commands on the host.

## Client and trust boundaries

All API operations use the official client image pinned in
`openqa/production/openqa-cli.sh`:

```text
registry.opensuse.org/devel/openqa/containers/tumbleweed@sha256:4d2f4736d18939aaaff5f5b0616d594255243a8974c33fd3a4731909ab44702e
```

The client container is unprivileged, read-only, drops capabilities, and
receives only the API credentials. It is a client, not an openQA server or
worker.

SSH is used only for the ISO stream. The dedicated authorized key must use a
forced command and disable agent forwarding, port forwarding, X11 forwarding,
and PTY:

```text
command="/usr/local/libexec/biglinux-openqa-receive-iso",no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty
```

The forced command accepts only the literal client command `iso-upload`. It
validates the ISO basename, exact byte count, SHA-256, extra bytes, temporary
file, lock, and atomic publication. It does not provide a shell or `sudo`.

## Daily flow

`build-iso.yml` builds one ISO, writes checksums, and uploads a private artifact
without openQA secrets. The reusable gate verifies that artifact, transfers the
same ISO to the receiver, and calls the API with:

```text
SCENARIO_DEFINITIONS_YAML=<checked-out scenario-definitions.yaml>
CASEDIR=<repository URL>#<full github.sha>
TEST_GIT_REFSPEC=<full github.sha>
NEEDLES_DIR=%%CASEDIR%%/openqa/needles
```

The API creates BIOS and UEFI scheduled products concurrently. Their JSON
responses provide scheduled-product IDs and successful job IDs. The gate then
uses the official monitor command for both sets and returns non-zero if any
mandatory job fails, is cancelled, incomplete, or cannot be verified.

The BIOS release plan includes the `applications` module with an explicit
critical filter for Dolphin, LibreOffice, GIMP, Brave, and BigLinux Control
Center. The UEFI release plan does not repeat the application module. The
unfiltered `applications` schedule remains available for a separate audit and
is not part of the mandatory release gate.

## Manual validation of a published ISO

The manual workflow accepts either:

1. the direct ISO release asset; or
2. every `.7z.*` part of a split asset.

For split assets it verifies the numeric sequence is complete, tests the archive,
extracts it, and then validates the exact ISO with both checksum files. The
manual workflow does not accept an artifact name from another workflow run;
candidate artifacts are supplied only through the reusable workflow call from
the current build.

## Diagnostics

The artifact is unique to the build and Actions run and contains:

- schedule JSON and logs;
- BIOS and UEFI job IDs;
- monitor output;
- per-job openQA archives;
- screenshots and video when produced;
- `autoinst-log.txt`;
- module details;
- application metrics;
- KVM evidence;
- the generated HTML report.

Archives are downloaded per job through the API. The worker pool is never copied
wholesale. Archive paths are checked for symlinks, special files, traversal, and
configured size limits before the report is generated.

## Rollback

Run the build with `publish_release=false` while investigating. If the
persistent service or workers are unhealthy, stop accepting candidates and
preserve active assets and job results. Revert the production workflow commit
through a reviewed Git revert; do not rewrite history. To remove the receiver,
disable the GitHub environment first, then remove only the dedicated forced
command key and installed receiver.
