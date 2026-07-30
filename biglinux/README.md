# Generated output — do not edit

Every file in this directory is rebuilt from scratch by
[`../.github/workflows/make-profiles.yml`](../.github/workflows/make-profiles.yml)
and committed by a bot. An edit here looks like it works and is silently
reverted on the next run.

Edit [`../sources/`](../sources/) instead, then push and wait for the bot commit.

The directory is committed because the ISO builders clone this repository and
read `biglinux/<edition>/` directly. `manjaro-tools` resolves a profile with
`find <repo> -maxdepth 2 -name <edition>`, so editions must stay exactly one
level below this directory, and this directory must keep its name: `gitrepo` and
the GitLab pipeline both derive it from the distro name.
