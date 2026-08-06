# BigLinux live GRUB

The first screen exposes only the four primary actions:

1. start BigLinux with the normal driver-selection path;
2. start without proprietary drivers;
3. open compatibility options;
4. restart the computer.

All hardware workarounds remain inside `Compatibility options`. Their stable
support codes are unchanged and continue to identify the exact workaround used.

Key files:

- `sources/common/overlays/live/usr/share/grub/cfg/grub.cfg`: platform, theme
  and dynamic boot options;
- `sources/common/overlays/live/usr/share/grub/cfg/kernels.cfg`: visible menu;
- `sources/common/overlays/live/usr/share/grub/cfg/variable.cfg`: theme directory,
  default entry and timeout;
- `SUPPORT-CODES.md`: public support-code catalog;
- `PARAMETER-REVIEW.md`: parameter policy and release-test boundary.

Navigation rules:

- submenu titles end in `>`;
- compatibility categories keep their stable support-code numbers;
- the first selectable entry in each support submenu returns to its parent;
- released support codes are append-only and keep their meaning;
- the theme displays the live, firmware and architecture context permanently;
- holding Shift disables the automatic boot timeout when supported;
- diagnostics include computer information and UEFI firmware setup.

Run the regression suite from the repository root:

```bash
pytest -q build-iso/tests/test_grub_live.py
```

## Graphical diagnostics and terminal limits

- The timeout ring and logo are separate components with the same calculated
  centre. The logo remains visible when the timeout is disabled.
- Computer information uses a dedicated graphical menu state. SMBIOS probing
  runs only after selecting support code `9.10`, so normal menu startup is not
  delayed and the theme remains active.
- The command line and entry editor share GRUB's single `gfxterm` window. The
  theme controls their common font, outer frame and geometry; the editor's
  internal border and instruction text are rendered by GRUB itself.
- The primary menu uses a fixed 620-pixel content width, so it remains compact
  on widescreen displays and readable at the minimum 800x600 mode.
- Compatibility uses a compact category overview and switches to a dedicated
  detailed layout only for long numbered support lists. Diagnostics uses a
  separate medium-height layout, while long lists retain a scrollbar.
- Computer information has its own 780-pixel layout and displays every field,
  including the active theme, without leaving a large unused area.


## Menu icon policy

Every static `menuentry` and `submenu` has an exclusive class derived from its
stable ID, for example `icon-biglinux-opt-2-4`. The corresponding 32x32 PNG uses
thin strokes and a small ID-derived marker, so no two visible static entries
share the same image.

The EFI scanner cannot know its entries while the ISO is being built. It
therefore consumes a pool of 32 exclusive EFI icons in detection order. If a
machine exposes more than 32 EFI executables, additional entries use the
transparent `void` class instead of repeating an icon.

Regenerate and synchronize the icon set after adding or renaming a menu entry:

```bash
./build-iso/generate-grub-icons.py
```

The generator is deterministic. Regression tests verify the class mapping,
PNG existence, byte-level uniqueness and synchronization across the common,
KDE and XivaStudio themes.
