# BigLinux GRUB support-code catalog

Support codes are stable public identifiers. Never renumber or reuse a released code. The risk column describes the breadth of the workaround, not the probability of damage.

| Code | Category | Symptom / purpose | Parameters | Risk |
|---|---|---|---|---|
| **2.1** | Video and desktop | Wayland with open-source drivers | `(session/driver selection)` | low |
| **2.2** | Video and desktop | Xorg with proprietary drivers | `(session/driver selection)` | low |
| **2.3** | Video and desktop | Xorg with open-source drivers | `(session/driver selection)` | low |
| **2.4** | Video and desktop | Black or corrupted screen — basic graphics | `nomodeset` | high |
| **2.5** | Video and desktop | Intel panel flickers — disable PSR | `i915.enable_psr=0` | medium |
| **2.6** | Video and desktop | Intel display is black or fails to refresh — disable FBC | `i915.enable_fbc=0` | medium |
| **2.7** | Video and desktop | Low-power Intel computer freezes — disable display C-states | `i915.enable_dc=0` | medium |
| **2.8** | Video and desktop | Intel PSR fails with firmware timings — use safest PSR values | `i915.psr_safest_params=1` | medium |
| **2.9** | Video and desktop | Intel PSR2 causes artifacts — disable selective fetch | `i915.enable_psr2_sel_fetch=0` | medium |
| **2.10** | Video and desktop | Older Intel eDP panel flickers — force 400 mV swing | `i915.edp_vswing=2` | medium |
| **2.11** | Video and desktop | Intel internal-panel brightness is missing — enable DPCD backlight | `i915.enable_dpcd_backlight=1` | medium |
| **2.12** | Video and desktop | Intel brightness controls are reversed — invert brightness | `i915.invert_brightness=1` | medium |
| **2.13** | Video and desktop | Intel graphics reports DMAR errors — bypass graphics IOMMU | `intel_iommu=igfx_off` | high |
| **2.14** | Video and desktop | Old Intel black screen or flip_done timeout — disable phantom S-Video | `video=SVIDEO-1:d` | low |
| **2.15** | Video and desktop | Backlight is missing — prefer native backlight | `acpi_backlight=native` | low |
| **2.16** | Video and desktop | Backlight is missing — use ACPI video backlight | `acpi_backlight=video` | low |
| **2.17** | Video and desktop | Backlight is missing — use vendor backlight driver | `acpi_backlight=vendor` | low |
| **2.18** | Video and desktop | Backlight driver causes a black screen — disable backlight interfaces | `acpi_backlight=none` | high |
| **2.19** | Video and desktop | AMD APU flickers under memory pressure — disable scatter/gather display | `amdgpu.sg_display=0` | medium |
| **2.20** | Video and desktop | AMD display freezes at flip_done — disable problematic DC feature | `amdgpu.dcdebugmask=0x10` | medium |
| **2.21** | Video and desktop | Recent AMD panel has PSR artifacts — disable PSR2 selective update | `amdgpu.dcdebugmask=0x200` | medium |
| **2.22** | Video and desktop | AMD Display Core fails — use legacy display path | `amdgpu.dc=0` | high |
| **2.23** | Video and desktop | AMD GPU has PCIe power errors — disable AMDGPU ASPM | `amdgpu.aspm=0` | medium |
| **2.24** | Video and desktop | AMD discrete GPU disappears — keep it powered | `amdgpu.runpm=0` | high |
| **2.25** | Video and desktop | AMD GPU hangs and does not recover — enable GPU recovery | `amdgpu.gpu_recovery=1` | medium |
| **2.26** | Video and desktop | Nouveau freezes during power transitions — keep NVIDIA powered | `nouveau.runpm=0` | high |
| **2.27** | Video and desktop | Nouveau acceleration crashes — disable acceleration | `nouveau.noaccel=1` | high |
| **2.28** | Video and desktop | Nouveau detects a phantom TV output — disable TV detection | `nouveau.tv_disable=1` | low |
| **2.29** | Video and desktop | AMD Southern Islands GPU — force AMDGPU driver | `radeon.si_support=0 amdgpu.si_support=1` | medium |
| **2.30** | Video and desktop | AMD Sea Islands GPU — force AMDGPU driver | `radeon.cik_support=0 amdgpu.cik_support=1` | medium |
| **2.31** | Video and desktop | AMD Southern Islands GPU — force Radeon driver | `amdgpu.si_support=0 radeon.si_support=1` | medium |
| **2.32** | Video and desktop | AMD Sea Islands GPU — force Radeon driver | `amdgpu.cik_support=0 radeon.cik_support=1` | medium |
| **2.33** | Video and desktop | Hybrid NVIDIA laptop has a black screen — integrated GPU only | `bignvidia=integrated` | medium |
| **2.34** | Video and desktop | Hybrid NVIDIA laptop needs external outputs — NVIDIA GPU primary | `bignvidia=nvidia` | high |
| **2.35** | Video and desktop | Legacy NVIDIA module reports IBT or ENDBR errors — disable IBT | `ibt=off` | high |
| **2.36** | Video and desktop | NVIDIA Turing or newer fails during GSP initialization — disable GSP | `nvidia.NVreg_EnableGpuFirmware=0` | medium |
| **2.37** | Video and desktop | Proprietary NVIDIA KMS fails — use Xorg without NVIDIA DRM KMS | `nvidia_drm.modeset=0` | high |
| **2.38** | Video and desktop | Proprietary NVIDIA framebuffer fails — disable nvidia_drm fbdev | `nvidia_drm.fbdev=0` | medium |
| **3.1** | Built-in keyboard, mouse and touchpad | Internal keyboard is missing after power-on — defer PS/2 probe | `i8042.probe_defer` | low |
| **3.2** | Built-in keyboard, mouse and touchpad | Keyboard or touchpad is missing — ignore firmware PnP data | `i8042.nopnp` | medium |
| **3.3** | Built-in keyboard, mouse and touchpad | Touchpad is detected incorrectly — disable PS/2 multiplexing | `i8042.nomux` | medium |
| **3.4** | Built-in keyboard, mouse and touchpad | Touchpad probe fails — skip PS/2 AUX loopback | `i8042.noloop` | medium |
| **3.5** | Built-in keyboard, mouse and touchpad | PS/2 controller is stuck — reset it during initialization | `i8042.reset` | medium |
| **3.6** | Built-in keyboard, mouse and touchpad | Keyboard or touchpad still missing — complete PS/2 recovery | `i8042.noloop i8042.nomux i8042.nopnp i8042.reset` | high |
| **3.7** | Built-in keyboard, mouse and touchpad | Elantech touchpad is missing — use primary PS/2 interface | `psmouse.elantech_smbus=0` | low |
| **3.8** | Built-in keyboard, mouse and touchpad | Synaptics touchpad fails over SMBus — use PS/2 interface | `psmouse.synaptics_intertouch=0` | low |
| **3.9** | Built-in keyboard, mouse and touchpad | Synaptics touchpad needs SMBus features — enable InterTouch | `psmouse.synaptics_intertouch=1` | medium |
| **3.10** | Built-in keyboard, mouse and touchpad | KVM or old mouse sends bad packets — use bare PS/2 protocol | `psmouse.proto=bare` | high |
| **3.11** | Built-in keyboard, mouse and touchpad | PS/2 mouse buttons are unreliable — use IntelliMouse protocol | `psmouse.proto=imps` | medium |
| **3.12** | Built-in keyboard, mouse and touchpad | PS/2 device sends repeated bad packets — reset after five errors | `psmouse.resetafter=5` | medium |
| **3.13** | Built-in keyboard, mouse and touchpad | Keyboard translation is broken — use direct PS/2 mode | `i8042.direct` | high |
| **3.14** | Built-in keyboard, mouse and touchpad | Firmware cannot control keyboard LEDs — use simple keyboard mode | `i8042.dumbkbd` | medium |
| **3.15** | Built-in keyboard, mouse and touchpad | PS/2 controller reports false timeouts — ignore timeout flag | `i8042.notimeout` | high |
| **3.16** | Built-in keyboard, mouse and touchpad | Firmware reports the keyboard as locked — ignore keyboard lock | `i8042.unlock` | medium |
| **3.17** | Built-in keyboard, mouse and touchpad | Internal keyboard remains unresponsive — reset keyboard device | `i8042.kbdreset` | medium |
| **3.18** | Built-in keyboard, mouse and touchpad | Acer Dritek hotkeys or keyboard are missing — enable Dritek extension | `i8042.dritek` | medium |
| **3.19** | Built-in keyboard, mouse and touchpad | Keyboard fails after suspend — do not restore i8042 state | `i8042.forcenorestore` | medium |
| **3.20** | Built-in keyboard, mouse and touchpad | ACPI PnP hides keyboard or touchpad — disable PNPACPI | `pnpacpi=off` | high |
| **4.1** | Storage and USB | NVMe times out or disappears — disable APST | `nvme_core.default_ps_max_latency_us=0` | medium |
| **4.2** | Storage and USB | NVMe firmware ACPI quirks cause errors — ignore NVMe ACPI | `nvme.noacpi=1` | high |
| **4.3** | Storage and USB | HP AMD laptop with KIOXIA NVMe has I/O errors — strict AMD IOMMU flush | `amd_iommu=fullflush` | medium |
| **4.4** | Storage and USB | SATA errors or freezes — disable NCQ | `libata.force=noncq` | medium |
| **4.5** | Storage and USB | SATA disk disappears while idle — disable mobile link power saving | `ahci.mobile_lpm_policy=1` | medium |
| **4.6** | Storage and USB | SATA fails after suspend — disable libata ACPI handling | `libata.noacpi=1` | high |
| **4.7** | Storage and USB | Old SATA disk repeatedly resets — limit link to 1.5 Gb/s | `libata.force=1.5Gbps` | high |
| **4.8** | Storage and USB | USB devices disconnect or freeze — disable USB autosuspend | `usbcore.autosuspend=-1` | medium |
| **4.9** | Storage and USB | USB disk or SATA adapter fails with UAS — use usb-storage | `module_blacklist=uas` | medium |
| **4.10** | Storage and USB | Old USB device is not detected — try legacy enumeration first | `usbcore.old_scheme_first=1` | low |
| **4.11** | Storage and USB | USB descriptor is slow — wait ten seconds | `usbcore.initial_descriptor_timeout=10000` | low |
| **4.12** | Storage and USB | USB storage is not ready immediately — delay use for ten seconds | `usb_storage.delay_use=10` | low |
| **4.13** | Storage and USB | Slow live USB cannot find its root filesystem — wait ten seconds | `rootdelay=10` | low |
| **4.14** | Storage and USB | Live storage appears late — wait indefinitely for root device | `rootwait` | medium |
| **5.1** | Audio, Wi-Fi, Ethernet and Bluetooth | Intel laptop has no sound — force legacy HDA driver | `snd_intel_dspcfg.dsp_driver=1` | medium |
| **5.2** | Audio, Wi-Fi, Ethernet and Bluetooth | Intel laptop needs SOF audio — force SOF driver | `snd_intel_dspcfg.dsp_driver=3` | medium |
| **5.3** | Audio, Wi-Fi, Ethernet and Bluetooth | Recent Intel laptop needs AVS audio — force AVS driver | `snd_intel_dspcfg.dsp_driver=4` | medium |
| **5.4** | Audio, Wi-Fi, Ethernet and Bluetooth | Audio pops or wakes slowly — disable HDA power saving | `snd_hda_intel.power_save=0` | low |
| **5.5** | Audio, Wi-Fi, Ethernet and Bluetooth | HDA audio has MSI interrupt errors — disable HDA MSI | `snd_hda_intel.enable_msi=0` | medium |
| **5.6** | Audio, Wi-Fi, Ethernet and Bluetooth | HDA audio stutters — use LPIB DMA position | `snd_hda_intel.position_fix=1` | medium |
| **5.7** | Audio, Wi-Fi, Ethernet and Bluetooth | HDA audio stutters — use position buffer | `snd_hda_intel.position_fix=2` | medium |
| **5.8** | Audio, Wi-Fi, Ethernet and Bluetooth | HDA codec model detection fails — use generic model | `snd_hda_intel.model=generic` | medium |
| **5.9** | Audio, Wi-Fi, Ethernet and Bluetooth | Intel Wi-Fi disconnects while idle — force active power scheme | `iwlmvm.power_scheme=1` | low |
| **5.10** | Audio, Wi-Fi, Ethernet and Bluetooth | Intel Wi-Fi power saving is unstable — disable it | `iwlwifi.power_save=0` | low |
| **5.11** | Audio, Wi-Fi, Ethernet and Bluetooth | Intel Wi-Fi 6 is unstable — disable 802.11ax | `iwlwifi.disable_11ax=1` | medium |
| **5.12** | Audio, Wi-Fi, Ethernet and Bluetooth | Intel Wi-Fi 5 mode is unstable — disable 802.11ac | `iwlwifi.disable_11ac=1` | high |
| **5.13** | Audio, Wi-Fi, Ethernet and Bluetooth | Old Intel Wi-Fi fails with 802.11n — disable 802.11n | `iwlwifi.11n_disable=1` | high |
| **5.14** | Audio, Wi-Fi, Ethernet and Bluetooth | Realtek RTW89 disconnects — disable PCIe L1 | `rtw89_pci.disable_aspm_l1=1` | low |
| **5.15** | Audio, Wi-Fi, Ethernet and Bluetooth | Realtek RTW89 disconnects — disable PCIe L1 substates | `rtw89_pci.disable_aspm_l1ss=1` | low |
| **5.16** | Audio, Wi-Fi, Ethernet and Bluetooth | Realtek RTW89 disappears while idle — disable Wi-Fi power mode | `rtw89_core.disable_ps_mode=1` | low |
| **5.17** | Audio, Wi-Fi, Ethernet and Bluetooth | Realtek RTW89 remains unstable — disable all RTW89 power saving | `rtw89_pci.disable_aspm_l1=1 rtw89_pci.disable_aspm_l1ss=1 rtw89_core.disable_ps_mode=1` | medium |
| **5.18** | Audio, Wi-Fi, Ethernet and Bluetooth | Bluetooth disappears while idle — disable btusb autosuspend | `btusb.enable_autosuspend=0` | low |
| **5.19** | Audio, Wi-Fi, Ethernet and Bluetooth | Atheros Wi-Fi disconnects while idle — disable ath9k power saving | `ath9k.ps_enable=0` | low |
| **5.20** | Audio, Wi-Fi, Ethernet and Bluetooth | Atheros Wi-Fi encryption fails — use software crypto | `ath9k.nohwcrypt=1` | medium |
| **6.1** | CPU, power, suspend and restart | Intel computer freezes while idle — limit Intel idle C-state | `intel_idle.max_cstate=1` | high |
| **6.2** | CPU, power, suspend and restart | ACPI idle computer freezes — limit processor C-state | `processor.max_cstate=1` | high |
| **6.3** | CPU, power, suspend and restart | AMD Ryzen freezes while idle — avoid MWAIT | `idle=nomwait` | medium |
| **6.4** | CPU, power, suspend and restart | CPU idle method hangs — force HLT idle | `idle=halt` | high |
| **6.5** | CPU, power, suspend and restart | Any CPU idle state hangs — disable cpuidle | `cpuidle.off=1` | critical |
| **6.6** | CPU, power, suspend and restart | Intel frequency driver causes freezes — disable intel_pstate | `intel_pstate=disable` | medium |
| **6.7** | CPU, power, suspend and restart | AMD frequency driver causes freezes — disable amd_pstate | `amd_pstate=disable` | medium |
| **6.8** | CPU, power, suspend and restart | Suspend uses s2idle but hardware supports S3 — prefer deep sleep | `mem_sleep_default=deep` | medium |
| **6.9** | CPU, power, suspend and restart | Deep sleep fails — prefer suspend-to-idle | `mem_sleep_default=s2idle` | medium |
| **6.10** | CPU, power, suspend and restart | Resume fails while restoring ACPI NVS — skip NVS restore | `acpi_sleep=nonvs` | high |
| **6.11** | CPU, power, suspend and restart | Old firmware resumes devices in wrong order — use legacy ordering | `acpi_sleep=old_ordering` | high |
| **6.12** | CPU, power, suspend and restart | Old video BIOS needs S3 resume call — use s3_bios | `acpi_sleep=s3_bios` | high |
| **6.13** | CPU, power, suspend and restart | Old video mode is not restored after suspend — use s3_mode | `acpi_sleep=s3_mode` | high |
| **6.14** | CPU, power, suspend and restart | ACPI SCI is disabled after resume — force SCI enable | `acpi_sleep=sci_force_enable` | high |
| **6.15** | CPU, power, suspend and restart | Closing the lid causes an immediate wake loop — initialize lid as open | `button.lid_init_state=open` | medium |
| **6.16** | CPU, power, suspend and restart | Clock, audio or resume problems — disable HPET | `nohpet` | medium |
| **6.17** | CPU, power, suspend and restart | Firmware hides a working HPET — force HPET | `hpet=force` | high |
| **6.18** | CPU, power, suspend and restart | Boot freezes during timer validation — skip IO-APIC timer check | `no_timer_check` | high |
| **6.19** | CPU, power, suspend and restart | Lockup watchdog initialization freezes — disable both lockup watchdogs | `nowatchdog` | high |
| **6.20** | CPU, power, suspend and restart | ACPI watchdog conflicts with native driver — ignore ACPI WDAT watchdog | `acpi_no_watchdog` | medium |
| **6.21** | CPU, power, suspend and restart | Computer hangs when restarting — use PCI reset | `reboot=pci` | medium |
| **6.22** | CPU, power, suspend and restart | Computer hangs when restarting — use ACPI reset | `reboot=acpi` | medium |
| **6.23** | CPU, power, suspend and restart | Computer hangs when restarting — use EFI reset | `reboot=efi` | medium |
| **6.24** | CPU, power, suspend and restart | Computer hangs when restarting — force triple-fault reset | `reboot=triple` | high |
| **6.25** | CPU, power, suspend and restart | Computer hangs when restarting — use keyboard-controller reset | `reboot=kbd` | high |
| **6.26** | CPU, power, suspend and restart | Restart hangs while stopping other CPUs — force reboot | `reboot=force` | high |
| **6.27** | CPU, power, suspend and restart | TSC clock is unstable — use ACPI PM clocksource | `clocksource=acpi_pm` | medium |
| **6.28** | CPU, power, suspend and restart | Default clocksource is unstable — use HPET clocksource | `clocksource=hpet` | medium |
| **6.29** | CPU, power, suspend and restart | Legacy app or virtual machine aborts on split lock — disable detection | `split_lock_detect=off` | high |
| **7.1** | Firmware, ACPI and UEFI | Old BIOS disables ACPI incorrectly — force ACPI | `acpi=force` | high |
| **7.2** | Firmware, ACPI and UEFI | ACPI causes failures but SMP is needed — keep ACPI only for CPU discovery | `acpi=ht` | critical |
| **7.3** | Firmware, ACPI and UEFI | ACPI prevents boot — disable ACPI completely | `acpi=off` | critical |
| **7.4** | Firmware, ACPI and UEFI | Firmware needs the legacy RSDT instead of XSDT — force RSDT | `acpi=rsdt` | high |
| **7.5** | Firmware, ACPI and UEFI | Legacy laptop brightness or Fn keys fail — report Linux to ACPI | `acpi_osi=Linux` | high |
| **7.6** | Firmware, ACPI and UEFI | Firmware selects a broken OS path — disable all ACPI OS strings | `acpi_osi=` | high |
| **7.7** | Firmware, ACPI and UEFI | Firmware vendor OS strings are broken — disable built-in vendor strings | `acpi_osi=!` | high |
| **7.8** | Firmware, ACPI and UEFI | Old NVIDIA Optimus firmware hangs — expose only Windows 2009 | `acpi_osi=! acpi_osi="Windows 2009"` | high |
| **7.9** | Firmware, ACPI and UEFI | Specific ASUS or Lenovo firmware fails — hide Windows 2012 | `acpi_osi="!Windows 2012"` | high |
| **7.10** | Firmware, ACPI and UEFI | Specific Gigabyte or AMD board wakes immediately — hide Windows 2015 | `acpi_osi="!Windows 2015"` | high |
| **7.11** | Firmware, ACPI and UEFI | Specific modern laptop sleep fails — hide Windows 2020 | `acpi_osi="!Windows 2020"` | high |
| **7.12** | Firmware, ACPI and UEFI | Firmware checks the ACPI revision incorrectly — override _REV | `acpi_rev_override=1` | high |
| **7.13** | Firmware, ACPI and UEFI | Legacy sensor driver cannot access ACPI resources — allow conflicts | `acpi_enforce_resources=lax` | critical |
| **7.14** | Firmware, ACPI and UEFI | Broken firmware publishes unusable 64-bit FADT address — use 32-bit address | `acpi_force_32bit_fadt_addr` | high |
| **7.15** | Firmware, ACPI and UEFI | Old NVIDIA nForce timer routing is broken — use timer override | `acpi_use_timer_override` | high |
| **7.16** | Firmware, ACPI and UEFI | Firmware provides a broken IRQ0 timer override — skip it | `acpi_skip_timer_override` | high |
| **7.17** | Firmware, ACPI and UEFI | UEFI crashes while mapping runtime services — avoid virtual map | `efi=novamap` | high |
| **7.18** | Firmware, ACPI and UEFI | UEFI runtime services crash Linux — disable EFI runtime services | `efi=noruntime` | critical |
| **7.19** | Firmware, ACPI and UEFI | UEFI file reads fail in chunks — disable EFI chunked reads | `efi=nochunk` | medium |
| **7.20** | Firmware, ACPI and UEFI | UEFI early PCI DMA shutdown breaks a device — keep bus mastering | `efi=no_disable_early_pci_dma` | critical |
| **7.21** | Firmware, ACPI and UEFI | UEFI memory is missing from the kernel map — add EFI memory map | `add_efi_memmap` | high |
| **7.22** | Firmware, ACPI and UEFI | Legacy BIOS hangs while querying disks — disable EDD | `edd=off` | medium |
| **8.1** | PCI, interrupts, DMA and IOMMU | PCI device is missing — reallocate bridge resources | `pci=realloc=on` | medium |
| **8.2** | PCI, interrupts, DMA and IOMMU | Firmware PCI resource windows are wrong — ignore ACPI _CRS | `pci=nocrs` | high |
| **8.3** | PCI, interrupts, DMA and IOMMU | Touchpad works with nocrs but Wi-Fi disappears — ignore and reallocate | `pci=nocrs pci=realloc=on` | high |
| **8.4** | PCI, interrupts, DMA and IOMMU | PCIe access or lspci freezes — disable MMCONFIG | `pci=nommconf` | high |
| **8.5** | PCI, interrupts, DMA and IOMMU | Device reports MSI or IRQ errors — disable PCI MSI | `pci=nomsi` | high |
| **8.6** | PCI, interrupts, DMA and IOMMU | PCIe AER floods the console — disable AER reporting | `pci=noaer` | medium |
| **8.7** | PCI, interrupts, DMA and IOMMU | Firmware assigns wrong PCI bus numbers — assign them in Linux | `pci=assign-busses` | high |
| **8.8** | PCI, interrupts, DMA and IOMMU | Broken driver never routes its PCI interrupt — route all IRQs early | `pci=routeirq` | high |
| **8.9** | PCI, interrupts, DMA and IOMMU | Early PCI scan causes a machine check — disable early scan | `pci=noearly` | critical |
| **8.10** | PCI, interrupts, DMA and IOMMU | PCI _CRS overlaps reserved firmware memory — honor E820 reservations | `pci=use_e820` | high |
| **8.11** | PCI, interrupts, DMA and IOMMU | Very old HP firmware has a broken PIRQ table — use BIOS PIRQ mask | `pci=usepirqmask` | high |
| **8.12** | PCI, interrupts, DMA and IOMMU | PCI config access via MMCONFIG fails — force mechanism 1 | `pci=conf1` | high |
| **8.13** | PCI, interrupts, DMA and IOMMU | Very old PCI config access fails — force mechanism 2 | `pci=conf2` | critical |
| **8.14** | PCI, interrupts, DMA and IOMMU | ACPI PCI IRQ routing blocks boot — ignore ACPI PCI routing | `pci=noacpi` | critical |
| **8.15** | PCI, interrupts, DMA and IOMMU | PCIe power management causes errors — disable ASPM | `pcie_aspm=off` | medium |
| **8.16** | PCI, interrupts, DMA and IOMMU | NVMe or discrete GPU still fails — disable PCIe port power management | `pcie_port_pm=off` | high |
| **8.17** | PCI, interrupts, DMA and IOMMU | Intel reports interrupt-remapping errors — disable remapping | `intremap=off` | critical |
| **8.18** | PCI, interrupts, DMA and IOMMU | DMA or IOMMU mapping errors — use software bounce buffers | `iommu=soft` | high |
| **8.19** | PCI, interrupts, DMA and IOMMU | AMD IOMMU breaks integrated graphics — use passthrough mappings | `iommu=pt` | medium |
| **8.20** | PCI, interrupts, DMA and IOMMU | Intel device still fails with IOMMU — disable Intel IOMMU | `intel_iommu=off` | critical |
| **8.21** | PCI, interrupts, DMA and IOMMU | AMD device still fails with IOMMU — disable AMD IOMMU | `amd_iommu=off` | critical |
| **8.22** | PCI, interrupts, DMA and IOMMU | AMD IOMMU needs immediate invalidation — use strict mode | `iommu.strict=1` | medium |
| **8.23** | PCI, interrupts, DMA and IOMMU | Boot freezes during IO-APIC setup — disable IO-APIC | `noapic` | critical |
| **8.24** | PCI, interrupts, DMA and IOMMU | Very old hardware freezes during early boot — disable local APIC | `nolapic` | critical |
| **8.25** | PCI, interrupts, DMA and IOMMU | Interrupt routing is broken — poll interrupt handlers | `irqpoll` | critical |
| **8.26** | PCI, interrupts, DMA and IOMMU | Known bad IRQ is disabled too aggressively — use IRQ fixup | `irqfixup` | high |
| **9.1** | Diagnostics and tools | Show detailed boot messages — disable Plymouth | `plymouth.enable=0 disablehooks=plymouth` | low |
| **9.2** | Diagnostics and tools | Trace kernel initialization — deep diagnostics | `debug ignore_loglevel initcall_debug log_buf_len=16M` | low |
| **9.3** | Diagnostics and tools | Open the installer directly | `biglinux.bootcmd=only-calamares` | low |
| **9.4** | Diagnostics and tools | Open the live desktop directly | `biglinux.bootcmd=boot-in-plasma` | low |
| **9.5** | Diagnostics and tools | Open a terminal directly | `biglinux.bootcmd=urxvt` | low |
| **9.6** | Diagnostics and tools | Boot to systemd multi-user mode | `systemd.unit=multi-user.target` | medium |
| **9.7** | Diagnostics and tools | Boot to systemd rescue mode | `systemd.unit=rescue.target` | medium |
| **9.8** | Diagnostics and tools | Run Memtest86+ | `not a Linux kernel entry` | low |
| **9.9** | Diagnostics and tools | Detect EFI bootloaders | `UEFI chainloader scan` | low |
| **9.10** | Diagnostics and tools | Show computer and boot information | `GRUB hardware information screen` | low |
| **9.11** | Diagnostics and tools | Open UEFI firmware settings | `UEFI firmware setup` | low |
