<p align="center">
  <img src="docs/images/header.webp" width="540" alt="header">
</p>

# BigLinux iso-profiles

> *"An ISO is just a list of packages and some files copied over them."*
> — someone who has never built an ISO

This repository holds two things that refuse to be separated: the **description**
of a BigLinux ISO (package lists and overlay files) and the **engine** that turns
that description into a bootable image (`build-iso/build-iso.sh`, which drives
`buildiso` over `biglinux/<edition>/`).

They live together on purpose. The description contains placeholders, labels and
directory names that only the engine understands. Keep them in two repositories
and someone eventually renames a placeholder in one, ships it, and discovers the
consequences four hours later — which is exactly how long a build takes before it
tells you it was doomed from the start.

---

## Yes, you can build your own

Let us get the intimidating part out of the way: **building a custom Linux
distribution is not the arcane ritual it looks like.** Not here, anyway. The hard
parts — bootloader, three squashfs layers, the live session, the installer, the
signing keys, the hundred small things that make a USB stick actually boot — are
already solved, tested, and shipped in this repository.

What is left for you is the interesting part: **deciding what goes in.**

Want an ISO with your own package selection, your own wallpapers, your own
defaults, your own name in the boot menu? That is a handful of text files and one
command:

```bash
./build-iso/build-local.sh kde
```

A realistic idea of the effort involved:

| What you want | What it takes |
|:---|:---|
| Add or remove packages | one line in a text file |
| Change a default setting | drop the config file into an overlay |
| Your own branding, hostname, live user | a few `sed` lines in `special-commands.sh` |
| A whole new edition of your own | a new directory and one variable in the workflow |
| No Linux machine at all | fork on GitHub, click **Run workflow**, download the ISO |

> [!TIP]
> With a bit of dedication — an afternoon of reading, honestly — you can produce a
> complete, bootable, installable, personalised ISO using the exact same tools and
> the exact same pipeline that build the official BigLinux images. Not a
> "remaster", not a script that hacks up someone else's ISO: **a real build, from
> real package lists, by the real engine.**
>
> Proof that this is not marketing: **XIVAStudio** is a full edition with its own
> branding, its own package trims and its own live user — and in this repository
> it is a directory of text files sitting next to `kde/`. Go read
> `sources/editions/xivastudio/`. That is the whole thing.

You will need patience for one thing only: a build takes a few hours, most of it
downloading packages. Start it, go do something else, come back to an ISO.

> [!NOTE]
> **Suggested reading order for a first custom ISO:**
> 1. **What an ISO is made of** — the three layers. Five minutes, saves hours.
> 2. **Two pipelines** — why your edit needs a bot commit before it reaches an ISO.
> 3. **What to edit** — the table that tells you which file to open.
> 4. **Building an ISO** — pick one of the three ways and go.
>
> Everything else in this file is reference material for when something surprises
> you. Something will.

---

## What an ISO is made of

A BigLinux ISO is not a folder of files. It is **three compressed filesystems
stacked on top of each other**, plus a bootloader to start the whole circus.
`manjaro-tools` builds each layer the same way: install a package list into a
chroot, then copy a directory of ready-made files over the result.

| Layer | Package list | Overlay | Ends up in |
|:---|:---|:---|:---|
| `rootfs` | `Packages-Root` | `root-overlay/` | the installed system |
| `desktopfs` | `Packages-Desktop` | `desktop-overlay/` | the installed system |
| `livefs` | `Packages-Live` | `live-overlay/` | **the live session only** |

Two consequences that are worth tattooing somewhere visible:

1. **A package list decides what exists. An overlay decides what a file says.**
   Want a program on the ISO? Package list. Want its config to differ from
   upstream's opinion? Overlay. Adding a config file to a package list does
   nothing at all, though it does look productive in a diff.

2. **`live-overlay/` never reaches the user's disk.** The installer copies
   rootfs + desktopfs and politely ignores livefs. So your beautiful fix works
   perfectly in the live session, survives the demo, and vanishes the moment
   somebody installs the system.

> [!WARNING]
> Number 2 is the most common mistake in this repository, and it is very good at
> hiding: everything you test in the live ISO looks correct. If a change must
> survive installation, it belongs in `root-overlay/`.

`Packages-Mhwd` is a fourth list but *not* a layer — it is the driver set `mhwd`
installs for whatever GPU the machine turns out to have.

**Vocabulary**, so the rest of this file makes sense:

- an **edition** (`kde`, `xivastudio`) is one complete set of those lists and overlays;
- a **profile** is the directory holding one edition.

---

## Two pipelines, and please do not confuse them

Half the confusion in this repository comes from people assuming there is one
pipeline. There are two, and they run at different times for different reasons.

```text
sources/                hand-written diffs, the only tree a person edits
    |
    |   PIPELINE 1   make-profiles.yml, weekly and on every push
    |                rebases Manjaro's lists, applies our add/remove files
    v
biglinux/<edition>/     complete profiles, generated and committed by a bot
    |
    |   PIPELINE 2   build-iso/build-iso.sh, on demand, ~4 h
    |                drives buildiso
    v
one bootable .iso       plus its .iso.pkgs list
```

| | Pipeline 1 | Pipeline 2 |
|:---|:---|:---|
| **Turns** | hand-written diffs → complete profiles | a complete profile → an ISO |
| **Runs** | weekly, and on every push | when a human asks for it |
| **Takes** | seconds | hours, and your patience |
| **Output** | a bot commit in `biglinux/` | one `.iso` + one `.iso.pkgs` |

> [!IMPORTANT]
> A change you make in `sources/` reaches an ISO **only after the bot has
> regenerated `biglinux/`**. Edit, push, wait for the bot commit, *then* build.
> Building immediately produces an ISO of the previous state and a puzzled face.

---

## The one rule

```text
sources/     ←  edit this
biglinux/    ←  generated by CI, never edit
build-iso/   ←  the build engine (edit like any other code)
```

`biglinux/` is rebuilt **from scratch** on every push and weekly, then committed
by a bot. Your careful edit there will work beautifully, be committed, pass
review, and be silently reverted on the next run. The directory is nevertheless
kept in git because the ISO builders clone this repository and read
`biglinux/<edition>/` directly — see [`biglinux/README.md`](biglinux/README.md).

---

## Layout

```text
sources/
├── common/                       applies to every edition
│   ├── Root-add    Root-remove     installed system packages
│   ├── Live-add    Live-remove     live session only
│   ├── Mhwd-add    Mhwd-remove     driver packages
│   ├── profile.conf                hostname, live user, services
│   └── overlays/root/ desktop/ live/   files shipped as-is
└── editions/
    ├── kde/                      Desktop-add + special-commands.sh
    └── xivastudio/               same, plus its own trims
```

### Why you edit diffs and not lists

Manjaro's `Packages-Root` is around 460 lines. Forking it means re-doing every
upstream rename, split and removal by hand, forever, and losing that argument
slowly. So this repository stores only the **difference** from upstream, and the
CI reapplies it weekly:

```text
  Manjaro shared/Packages-Root        common/Root-remove        common/Root-add
  ─────────────────────────────       ──────────────────        ───────────────
    firefox                                nano                  biglinux-config
    nano                                                         micro
    systemd
          │                                  │                          │
          └────── grep -vF -f Root-remove ────┘                          │
                             │                                          │
                             └──────────── cat Root-add >> ─────────────┘
                                            │
                                            ▼
                              biglinux/kde/Packages-Root
                                    firefox
                                    systemd
                                    biglinux-config
                                    micro
```

Same three steps for `Root`, `Live` and `Mhwd`. When Manjaro renames a package,
nobody here does anything — the weekly run absorbs it.

<details>
<summary><b><code>Packages-Desktop</code> is the exception, of course</b></summary>

There is always one. `Packages-Desktop` has no Manjaro base of its own, so
`Desktop-add` is **written over it** rather than appended to it.

That is not the whole story either: `editions/kde/special-commands.sh` then
grafts four sections copied verbatim out of Manjaro's own KDE profile —
`## Printing`, `## Xorg Server and Graphics`, `## Xorg Input Drivers` and
`## Misc`. Which means `xorg-server` and the entire printing stack are *not* in
`Desktop-add`, they arrive from upstream.

So before you conclude "this package is missing" and add it: look in
`special-commands.sh` first. It is probably already there, twice.

</details>

---

## What to edit

Paths relative to `sources/`.

| Goal | Edit |
|:---|:---|
| Add a package to every edition | `common/Root-add` |
| Drop a Manjaro package from every edition | `common/Root-remove` |
| Change a KDE desktop package | `editions/kde/Desktop-add` |
| Change a live-session-only package | `common/Live-add` / `common/Live-remove` |
| Change a driver package | `common/Mhwd-add` / `common/Mhwd-remove` |
| Ship a file in the installed system | `common/overlays/root/` |
| Ship a file only in the live session | `common/overlays/live/` |
| Add an edition | new dir in `editions/` with `Desktop-add`, then list it in `editions` in the workflow |

Then: push → wait for the bot commit → build an ISO. In that order.

---

## Building an ISO

On your machine, on GitHub Actions or on GitLab — all three run the exact same
engine, `build-iso/build-iso.sh`. There is no second copy of the build logic
anywhere, so there is no second copy of its documentation either:

```bash
./build-iso/build-local.sh kde
```

The other two ways to start a build, the environment contract, the
stage-by-stage walkthrough and the troubleshooting table are in
[`build-iso/README.md`](build-iso/README.md).

---

## Three things that surprise everybody exactly once

> [!CAUTION]
> **Removal matches a *substring*, not a package name.**
> `*-remove` feeds `grep -vF -f`, so an entry drops every line *containing* it.
> This is deliberate and useful: `libva-mesa` is the prefix that removes
> Manjaro's `libva-mesa-driver`. It is also how `micro` cheerfully removes
> `libmicrohttpd`. Use the longest prefix that still catches what you want.

> [!NOTE]
> **`kde` is built before `xivastudio`, and that is load-bearing.**
> `editions/xivastudio/special-commands.sh` appends the *generated* KDE desktop
> list to its own, so the order of the workflow's `editions` variable is not
> cosmetic. Reorder it alphabetically and xivastudio ships a desktop with
> impressively few packages in it.

> [!NOTE]
> **`KERNEL` is a placeholder, not a package.**
> `build-iso/build-iso.sh` expands `KERNEL-nvidia-580xx` into
> `linux618-nvidia-580xx` (or `linux-xanmod-nvidia-580xx`) for the kernel being
> built. Leave it as `KERNEL`. Helpfully "fixing" it to a real version pins the
> ISO to that kernel until someone notices.

---

## Reference desk

<details>
<summary><b>Why is there a file called <code>repo_info</code> with a version in it?</b></summary>

It is not documentation, and nothing reads it for information. `manjaro-tools`
locates a profile repository by *searching for a file with that name*. Delete it
and the tooling stops finding this repository at all.

</details>

<details>
<summary><b>Which overlay goes where, again?</b></summary>

| Overlay | Reaches |
|:---|:---|
| `root-overlay/` | the installed system |
| `desktop-overlay/` | the desktop image |
| `live-overlay/` | the live session only |

The CI renames `common/overlays/root/` to `root-overlay/` on the way out,
because those are the names `manjaro-tools` insists on. This is why the source
tree and the generated tree use different names for the same thing.

</details>

<details>
<summary><b>Where do the pacman repositories come from?</b></summary>

From [`build-iso/build-iso.sh`](build-iso/build-iso.sh), and nowhere else. Its
`append_build_repos` writes them into the pacman config `buildiso` uses, in
priority order, and `set-biglinux-branch.sh` puts the matching list in the ISO's
own `pacman.conf` so the installed system updates from what it was built with.

The profiles ship no `user-repos.conf` and no `pacman-default.conf`. The second
is **never read** by manjaro-tools at all, and the first *is* — it gets
concatenated onto the config the engine just wrote, which registered
`[biglinux-stable]` twice and had pacman drop one copy mid-build. The engine
removes any it finds. An unread config file is bad; a half-read one is worse.

</details>
