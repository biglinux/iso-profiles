# BigLinux production openQA gate

The production workflow does not start openQA in GitHub Actions. It uploads the
candidate ISO to a restricted SSH receiver on a persistent openQA host, invokes the
server's existing `openqa-cli`, and collects the two job archives after both plans
finish.

## Persistent host

Install and configure the distribution packages for `openQA`, `openQA-client`,
`os-autoinst`, QEMU, OVMF, `jq`, `tar`, and an NTP client. Keep these services and
paths persistent:

```text
openqa-webui
openqa-scheduler
/var/lib/openqa/share/factory/iso
/var/lib/openqa/testresults
/var/lib/openqa/pool
```

The openQA client configuration used by the CI SSH account must contain a dedicated
API key and secret with only the permissions needed to schedule, monitor, and archive
BigLinux jobs. The key is stored on the persistent host, never in the GitHub runner.
The host must expose HTTPS with a certificate trusted by that host's client.

Create the group named by `OPENQA_GROUP`, the `biglinux-kvm` worker class, and two
healthy workers. Each worker must be an independent QEMU worker with read/write
access to `/dev/kvm`, at least 4 GiB RAM and two vCPUs per job, persistent result
storage, and OVMF firmware. The scenario's QEMU command must contain
`-enable-kvm`; `QEMU_NO_KVM=0` is passed by the gate and a missing KVM device must
make the job fail rather than silently become TCG.

Keep retention/cleanup enabled for old jobs and ISO assets. Monitor free space in
the asset, result, pool, and worker cache filesystems. Synchronize clocks on the web
host and workers.

## Restricted ISO receiver

Install `receive-iso.sh` as the forced command for a dedicated SSH key, with the
receiver's `BIGLINUX_RECEIVER_ISO_DIR` set to the persistent openQA ISO asset
directory. The authorized key must include:

```text
command="/usr/local/libexec/biglinux-openqa-receive-iso",no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty
```

The installed command must reject every `SSH_ORIGINAL_COMMAND` except
`iso-upload`, accept only a safe `.iso` basename, enforce the declared size and
SHA-256, reject extra bytes, and publish with an atomic hard link only after the
complete temporary file validates. Give the receiver group write access to staging
and the worker group read access to published assets. Do not allow the receiver key
to open a shell or run `sudo`.

## GitHub configuration

Create the protected environment `openqa-production` and add only these secrets:

```text
OPENQA_SSH_PRIVATE_KEY
OPENQA_KNOWN_HOSTS
OPENQA_TEST_PASSWORD
```

Add these non-secret environment variables:

```text
OPENQA_URL
OPENQA_SSH_HOST
OPENQA_SSH_USER
OPENQA_SSH_PORT
OPENQA_GROUP
OPENQA_WORKER_CLASS
OPENQA_REMOTE_ISO_DIR
```

`OPENQA_KNOWN_HOSTS` must contain the reviewed host key. The workflow requires
strict host-key checking, writes the private key with mode `0600` in runner temp,
and removes both temporary SSH files in an `always()` step. It does not print the
secret values or pass them to the ISO build container.

## Daily flow

`build-iso.yml` creates checksums and uploads the candidate artifact without release
secrets. The reusable production workflow verifies the checksums, validates the
persistent API and worker class, uploads the ISO, and starts `release_bios` and
`release_uefi` concurrently using the exact `github.sha` for `CASEDIR`, needles, and
`TEST_GIT_REFSPEC`. BIOS includes the broad application audit; UEFI covers live boot,
installation, reboot, login, health, and Brave. The GitHub release job depends on the
gate result and therefore cannot publish after a failed or incomplete gate.

The artifact contains scheduler logs, job IDs, openQA archives, videos, screenshots,
autoinst logs, and the generated HTML report. The archive is collected per job; the
worker pool is not copied wholesale.

## Rollback

Revert the commit that changes `build-iso.yml` back to the previous reusable workflow
reference. The persistent server's openQA jobs and assets remain untouched. To remove
the receiver, first disable the GitHub environment and then remove only the dedicated
forced-command key and its installed receiver, preserving the openQA asset directory.
