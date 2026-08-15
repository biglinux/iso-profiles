# build-iso — the ISO build engine

> *"It's one script. How complicated can it be?"*

One script, `build-iso.sh`, turns the profiles in this repository into a bootable
BigLinux or BigCommunity ISO. Everything else in this directory is documentation
and thin wrappers around it.

**Every** generator runs this same code: the official GitLab pipeline, the GitHub
Actions workflow, the Build ISO GUI (`gitrepo`) and your terminal. There is no
second copy of the build logic, no "the CI does it slightly differently", no
mystery divergence to debug at 2 a.m.

---

## Three ways to build

### 1. On your machine

Needs `podman` or `docker`. Nothing is installed on your system — the build
happens inside the official container.

From a clone of this repository — yours or upstream's, the commands are the same:

```bash
./build-iso/build-local.sh kde
```

The ISO lands in `./output`. The first build downloads a *lot*: budget 1–2 hours
and something else to do.

<details>
<summary><b>Why does it copy the checkout before building?</b></summary>

Because the engine **edits the profile in place** (see `configure_profile`
below). Building directly in your clone would leave it full of branch-specific
rewrites, and the next `git status` would be a small crime scene.

So `build-local.sh` copies the checkout to a scratch directory and builds from
the copy. Two details that look arbitrary but are not:

- The copy goes **next to** the checkout, not under `./output` — because
  `./output` is *inside* the checkout, and copying a directory into itself is a
  thing `cp` refuses to do (correctly, and with feeling).
- Not in `/tmp` either — that is RAM-backed on most systems, and a profile tree
  plus an ISO is not something you want resident in memory.

</details>

### 2. On GitHub

No Linux machine required. Fork this repository, enable Actions in your fork,
then **Actions → Build ISO → Run workflow** and pick edition, kernel and
branches.

The finished ISO is attached to a release in your fork — as a single file when it
fits GitHub's 2 GiB asset limit, otherwise split into `.7z.001` / `.7z.002`
parts. Extract with 7-Zip, Ark, or:

```bash
7z x file.7z.001
```

### 3. On GitLab

Copy `build-iso/gitlab-ci.example.yml` to `.gitlab-ci.yml` in your fork. The
runner must allow privileged containers.

The official release pipeline lives in its own repository (`build-iso`) and runs
this same engine — it adds only the parts a fork usually does not want:
publishing over SSH, a torrent, and chat notifications. Its README documents the
four values a fork changes.

---

## What the engine actually does

Here is the honest version: **`buildiso` builds the ISO.** It comes from
`manjaro-tools` and it does the heavy lifting. Almost all of `build-iso.sh` is
about *convincing `buildiso` to do the right thing* — configured where upstream
offers a setting, patched in `/usr/lib/manjaro-tools/` where it does not.

```text
resolve_kernel          lts -> linux612
      |
      v
prepare_host            build tools, keyrings, loop devices
      |
      v
configure_build_repos   our repositories into the build pacman config
      |
      v
patch_manjaro_tools     edit util-iso.sh and util-iso-image.sh
      |
      v
configure_profile       rewrite the profile in place
      |
      v
run_build               buildiso  <-- the four hours happen here
      |
      v
collect_output          name the ISO, move it to WORK_PATH
```

Stage by stage, in the order `main()` runs them:

| Stage | What it does | Why it has to exist |
|:---|:---|:---|
| `resolve_kernel` | turns `lts` / `latest` / `xanmod` into a real package name (`linux612`, `linux-xanmod`) | the profiles carry the placeholder `KERNEL`, not a version, so a kernel bump needs no commit |
| `prepare_host` | installs the build tools and keyrings, creates loop devices, writes `manjaro-tools.conf` | the container is disposable and ships none of this |
| `configure_build_repos` | adds the BigLinux repositories to the *build* pacman config, drops the profile's `user-repos.conf`, sets the compression | the chroots must be able to install our packages, not only Manjaro's — from one list, since manjaro-tools concatenates the profile's onto this one and pacman rejects the repeats |
| `patch_manjaro_tools` | edits `util-iso.sh` / `util-iso-image.sh`: profile path, volume label, kernel check, image cleanups, live-user fix | none of these have a configuration knob upstream |
| `configure_profile` | rewrites the *profile* in place: branch mirrors, volume label, `KERNEL` placeholders, `/etc/big-release` | the profile in git is branch-agnostic; the build makes it concrete |
| `run_build` | `buildiso -p <edition> -b <branch> -k <kernel>` | the actual four hours |
| `collect_output` | writes the **published** ISO name, moves it and its `.pkgs` into `WORK_PATH` | every publisher ships the file under this name; see *The published name* below |

> [!IMPORTANT]
> Because `configure_profile` edits the checkout, **always build from a
> disposable clone.** All three wrappers already do this for you; the warning is
> for whoever decides to be clever and call `build-iso.sh` directly.

### Why the script is so full of `grep`

Every stage verifies its own result: a `grep -q` after each `sed`, and
`assert_absent` for "this pattern must now be gone". That is not paranoia, it is
arithmetic — a build costs four hours, and a `sed` that silently matched nothing
(upstream moved the file, upstream renamed the function, upstream reformatted the
line) does not announce itself. It waits, patiently, and then hands you an
unbootable ISO.

> [!NOTE]
> `assert_absent()` exists for a specific and genuinely nasty reason: `! grep -q
> …` **cannot** assert absence in a script with `set -e`. POSIX says errexit is
> ignored for a pipeline starting with `!`, so the failure is discarded and the
> build carries on regardless. Try it:
>
> ```bash
> bash -c 'set -eo pipefail; ! grep -q x <<< "x"; echo "still here"'
> # prints: still here
> ```
>
> Every negative check in this directory goes through `assert_absent()` (or an
> explicit `if … then exit 1`), and a test enforces that.

---

## The environment contract

`build-iso.sh` runs **as root inside the build container**
(`xivastudio/biglinux_build_package`), edits the profile in place, and leaves
exactly one `*.iso` — plus its `*.iso.pkgs` — in `WORK_PATH`.

Only the edition is required. Everything else has a default that is correct for a
release build:

| Variable | Default | Meaning |
|:---|:---|:---|
| `EDITION` (or `$1`) | — | **required.** Profile to build (`kde`, `xivastudio`, …) |
| `KERNEL` | `lts` | `oldlts` \| `lts` \| `latest` \| `xanmod` \| `xanmod-lts` |
| `MANJARO_BRANCH` | `stable` | `stable` \| `testing` \| `unstable` |
| `BIGLINUX_BRANCH` | `stable` | `stable` \| `testing` \| `development` (additive: testing sits *above* stable) |
| `BIGCOMMUNITY_BRANCH` | `stable` | same, bigcommunity only |
| `RELEASE_TAG` | today | date stamped into `/etc/big-release` and the ISO name |
| `WORK_PATH` | `<checkout>/output` | where the ISO ends up |
| `DISTRONAME` | detected | `biglinux` or `bigcommunity`, from the profile dirs |
| `PROFILES_ROOT` | the checkout | build profiles living in another checkout |
| `BUILD_MIRROR` | `http://mirrors.manjaro.org/repo` | the one mirror the whole Manjaro package set comes from; trailing slashes are stripped |
| `BIGLINUX_REPO_HOST` | `repo.biglinux.com.br` | host of the BigLinux repositories the **build** installs from |
| `COMMUNITY_REPO_HOST` | `repo.communitybig.org` | same for the community repositories; bigcommunity only |
| `MESA_TKG` | `false` | swap mesa for the TKG builds, on `latest` / `xanmod*` only (see `configure_profile`) |

> [!NOTE]
> `BIGLINUX_REPO_HOST` reaches both the build and the `[biglinux-testing]` section
> written into the ISO's own pacman configuration. It does **not** reach
> `[biglinux-stable]`, which the profile ships as a literal file — so a fork
> serving its own packages still has to edit the `Server` line in
> `<edition>/root-overlay/etc/pacman.conf` and `live-overlay/etc/pacman.conf`.

### How a kernel selector becomes a package

| You ask for | Resolved from | You get |
|:---|:---|:---|
| `lts` | kernel.org's longterm feed, newest entry | `linux612`, … |
| `oldlts` | kernel.org's longterm feed, second entry | the previous longterm |
| `latest` | the `linux-latest` meta package's `kernelver` | `linux71`, … |
| `xanmod`, `xanmod-lts` | fixed names | `linux-xanmod[-lts]` |

Whatever comes out fills the `KERNEL` placeholders in the `Packages-*` files. So
`KERNEL-nvidia-580xx` becomes `linux612-nvidia-580xx` without anyone editing a
list.

### The published name

`collect_output` writes the name the ISO is published under, and it is the only
place that decides it. The publishers move the file; none of them renames it.

```text
  product        tier              date         kernel id
  ────────       ──────────────    ──────────   ─────────
  biglinux   _DEVELOPMENT_gnome _  2026-07-31 _ k612       .iso
  └ distro or     └ empty for a       └ from      └ k612, xanmod71
    xivastudio      release             RELEASE_TAG
```

| Built from | Named |
|:---|:---|
| stable + stable | `biglinux_<date>_k612.iso` |
| Manjaro stable + our testing | `biglinux_TESTING_<date>_k612.iso` |
| Manjaro stable + our development | `biglinux_DEVELOPMENT_<date>_k612.iso` |
| Manjaro testing | `biglinux_DEVELOPMENT_ManTesting_<date>_k612.iso` |
| Manjaro unstable | `biglinux_DEVELOPMENT_ManUnstable_<date>_k612.iso` |

Both branches vote, and Manjaro's is asked first: a non-stable Manjaro makes the
build a development one whatever our own branch says. `kde` carries no flavour
segment because it is the default edition and `xivastudio` is its own product;
any other edition is inserted as `_<edition>`, *inside* the tier
(`biglinux_TESTING_gnome_…`, never `biglinux_gnome_TESTING_…`).

> [!NOTE]
> `development` is a name, not a repository set — BigLinux publishes no
> development repository, so such a build installs from testing and differs only
> here. Everything downstream of `read_inputs` sees `testing`, including
> `/etc/big-release`.

> [!IMPORTANT]
> A publisher that renames this file re-implements the table above, and the two
> copies drift. That is exactly how the GitHub workflow came to publish
> `biglinux_STABLE_xivastudio_<date>.iso` while the GitLab pipeline published the
> same build as `xivastudio_<date>.iso`. Change the scheme here.

---

## The helper scripts

Every one of these exists because a real ISO shipped broken without it. They are
not refactoring opportunities. **Read a script's header before touching it** —
each header documents the exact failure it prevents.

<details open>
<summary><b><code>patch-live-setup.sh</code> — the important one</b></summary>

`manjaro-live-setup` creates the live user at build time. Unfortunately
`useradd -m` can fail to copy `/etc/skel` across the container's overlayfs —
reporting `Bad file descriptor` and then **not failing the build**, which is the
worst of both worlds.

The live home ends up without the big-skel Plasma configuration, and the session
boots to a **black screen** with no plasmashell. This script re-syncs the skel
afterwards and fails the build if the live home is still incomplete, so the
broken ISO is never published.

</details>

<details>
<summary><b><code>set-manjaro-branch.sh</code> — the branch that lies</b></summary>

The profile hardcodes `stable` in `/etc/pacman.d/mirrorcdn`, and that file is
included *before* the mirrorlist, so it wins. A testing ISO would therefore
install and then immediately update itself from stable, quietly mixing two
branches on the user's disk. This points it at the branch actually being built
(biglinux profiles only).

</details>

<details>
<summary><b><code>set-biglinux-branch.sh</code> — testing above stable</b></summary>

A testing ISO must ship `[biglinux-testing]` *above* `[biglinux-stable]`. Miss
that and the installed system updates from stable alone — so the user never
receives the testing packages their testing ISO was built with.

</details>

The TKG mesa swap has no script of its own: it is three commands inline in
`configure_profile`, behind `MESA_TKG=true` and limited to `latest` / `xanmod*`.

---

## Tests

`tests/` exercises these scripts against real fixtures: the black-screen
regression, the branch rewrites, and `build-local.sh` driven against a **stub
container engine** — so the wrapper's logic is covered in half a second instead
of four hours.

From the repository root:

```bash
pytest build-iso/tests/            # behaviour
shellcheck -x build-iso/*.sh       # must be clean
```

> [!NOTE]
> `shellcheck` is clean and expected to stay clean. The three
> `# shellcheck disable=SC2016` directives are deliberate, not laziness: a
> `$arch` written into a `pacman.conf`, or a `$1` written into a patched
> `manjaro-tools` function, must reach the file **unexpanded**. Those single
> quotes are load-bearing.

---

## Troubleshooting

| Symptom | What is actually happening |
|:---|:---|
| **Build dies on disk space** | The chroots need ~15 GB under `/var/lib/manjaro-tools`, plus the ISO under `/var/cache/manjaro-tools`. On GitHub the workflow already mounts the runner's big `/mnt` disk there. |
| **Packages older than expected** | The entire Manjaro package set comes from `BUILD_MIRROR` — `mkchroot` rewrites the mirrorlist down to that single URL. If that mirror lags, everything lags. Point `BUILD_MIRROR` at a fresh one. |
| **`404` retrieving a package pacman just resolved** | The database and the package files disagreed: the database named a version the mirror no longer serves. The known cause was a trailing slash in `BUILD_MIRROR`, which turned every URL into `repo//stable/…` — behind a CDN, an empty path segment is a cache key of its own, and the `core.db` cached under it was weeks old. `read_inputs` strips trailing slashes now; check the `--> mirror:` line of the build log for any other `//`. |
| **`could not register '<repo>' database (database already registered)`** | Two sections declared the same repository, and pacman kept the first. `append_build_repos` is the only place that may name one; if a profile ships a `user-repos.conf`, manjaro-tools concatenates it onto that same file. `configure_build_repos` deletes it for that reason. |
| **xanmod version in the ISO name** | Only knowable *after* the build, so it is read back from the `.pkgs` list, producing names like `…_xanmod71.iso`. Not a bug, just chronology. |
| **Black screen in the live session** | See `patch-live-setup.sh` above. The build is supposed to *fail* rather than produce one — so if you are looking at a black screen, somebody bypassed the engine. |
