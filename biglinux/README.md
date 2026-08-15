# Generated output — do not edit

> [!CAUTION]
> Every file in this directory is rebuilt **from scratch** by
> [`../.github/workflows/make-profiles.yml`](../.github/workflows/make-profiles.yml)
> and committed by a bot.
>
> An edit here will work. It will pass review. It will be committed. And it will
> be silently reverted on the next run, with no error, no warning and no clue as
> to why your fix stopped existing.

Edit [`../sources/`](../sources/) instead, then push and wait for the bot commit.

## Then why is generated output committed to git?

Because the ISO builders clone this repository and read `biglinux/<edition>/`
directly — there is no build step on their side to generate it for them.

Two constraints follow from that, and both are easy to break by tidying up:

- **Editions must stay exactly one level below this directory.**
  `manjaro-tools` resolves a profile with `find <repo> -maxdepth 2 -name <edition>`.
  One extra level of nesting and the profile becomes invisible.
- **This directory must keep its name.** Both `gitrepo` and the GitLab pipeline
  derive it from the distribution name, so `biglinux/` is not a label — it is an
  interface.
