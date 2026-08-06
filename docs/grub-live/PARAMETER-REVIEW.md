# Review policy for BigLinux live boot parameters

This document records the policy behind the numbered GRUB support menu. The
visible codes are a support interface: once published, a code must not be
renumbered or reused for another workaround.

## Normal boot

The recommended entry uses Wayland, the normal proprietary-driver selection
path and only one generic kernel policy override:

```text
nmi_watchdog=0
```

The remaining tokens are required by the live image, the visual boot path or
BigLinux userspace:

```text
misobasedir=... misolabel=... rw wayland
 driver=nonfree nouveau.modeset=0
 quiet splash loglevel=3 systemd.show_status=auto rd.udev.log_level=err
```

Language, keyboard, timezone, clock, custom and loopback parameters are passed
through `${kopts}` to every BigLinux Linux entry.

## Recovery-only parameters

A valid parameter is not automatically suitable for the normal path. The
numbered menu keeps potentially useful workarounds isolated by symptom so that
support can identify which change solved the problem. Examples intentionally
kept only as recovery options include:

- `nomodeset`, `video=SVIDEO-1:d` and driver-specific display controls;
- `nohpet`, `hpet=force`, `no_timer_check` and clock-source overrides;
- `nowatchdog` and `split_lock_detect=off`;
- `acpi_osi=` variants, `acpi=off`, `pci=noacpi` and `nolapic`;
- IOMMU, APIC, IRQ, PCI resource and PCI power-management workarounds;
- storage, USB, input, audio and network module parameters.

High and critical risk in `SUPPORT-CODES.md` describes how broadly an option
changes the machine, not the likelihood of physical damage. Critical entries
may remove CPUs, power management, interrupt routing, DMA isolation or an
entire firmware subsystem and are last-resort choices.

`split_lock_detect=off` remains only as code **6.29** for legacy applications or
virtual machines that abort when split-lock detection is active. It removes a
CPU protection and can let one process severely reduce responsiveness.

## Rejected legacy or normal-path parameters

The implementation does not restore the following legacy tuning in the normal
entry:

| Parameter | Decision |
|---|---|
| `i915.semaphores=1` | Removed from current i915; do not expose. |
| `i915.modeset=1`, `radeon.modeset=1` | Do not force current driver defaults. |
| `noapci` | Invalid spelling; use a specific documented option such as `noapic` or `pci=noacpi`. |
| `noacpi` | Ambiguous legacy form; use subsystem-specific recovery entries. |
| `nomce` | Do not hide hardware-error reporting on the supported x86-64 target. |
| `pnpbios=off` | Obsolete target; use `pnpacpi=off` or a specific i8042 workaround. |
| `clearcpuid=514` | Debug mechanism that disables a CPU feature; not a production default. |
| `audit=0` | Disables audit for the entire boot and cannot be reversed before restart. |
| `cryptomgr.notests` | Disables cryptographic implementation self-tests. |
| `rcupdate.rcu_expedited=1` | Global RCU policy with no generic live-desktop justification. |
| `skew_tick=1` | Specialized large-system tuning, not a low-cost desktop optimization. |
| `nosoftlockup`, `tsc=nowatchdog` | Do not disable diagnostics globally. |

## Validation boundary

Static validation and GNU GRUB 2.14 emulation can prove syntax, menu structure,
theme loading and navigation logic. They cannot prove that every kernel/module
parameter fixes the named hardware symptom. Before release, build at least one
KDE and one XivaStudio ISO and test BIOS, UEFI, loopback/Ventoy, Memtest86+ and
representative Intel, AMD and NVIDIA systems.
