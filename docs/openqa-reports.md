# openQA reports

A gate run publishes a report whether its tests pass, fail or never start. This
page describes what is published and what the report promises.

## What a run publishes

`openqa.yml` writes one report per plan, and `openqa-report.yml` writes one for
the whole run. The run report waits for `static`, `plan` and
`applications-aggregate` with `if: always()`, and so does every one of its
generate, summary and upload steps. Putting the condition on the job alone is
not enough, because each step otherwise inherits an implicit `success()`.

The artifact `biglinux-iso-validation-<build>-<run>-<attempt>` contains:

| File | Content |
|---|---|
| `biglinux-iso-validation.pdf` | detailed report, or a short emergency PDF |
| `biglinux-validation-report.html` | self-contained HTML report |
| `RESULTADO.md` | the summary, also written to the Actions run page |
| `RESULTADO.json` | verdict, counts, gaps and which formats were produced |
| `run-status.json` | run identity and the state of the executor, jobs and steps |

The report job writes an emergency summary before it checks out any code. When
the finalizer is available, it first writes every basic format and only then
tries the detailed renderers; each file is replaced atomically. If `fpdf2` or
Pillow is missing, or rendering fails, a plain-text PDF and the short formats
are still written. In that case the finalizer exits non-zero, so that the
degraded report is noticed. The PDFs use the format's standard fonts, so
characters outside that set are replaced. HTML, Markdown and JSON keep Unicode.

## The verdict is not the renderer's exit status

A failed test run can produce a perfectly good report: `finalize_report.py`
exits zero and the document says **Falhou**. The gate requires the plans, the
aggregation and the report publication all to succeed. A missing or degraded
report also blocks the release.

The verdict accounts for:

- each module's own result, even when every one of its `details` is positive;
- application failures, executor exits and workflow dependencies;
- `softfail`, `skipped` and inconclusive states, which are preserved as they are.

Evidence that is missing or unreadable never becomes a pass and never
disappears from the report. That covers modules without `details`, partial
results without `vars.json`, invalid JSON or UTF-8, scheduled modules that
never ran, and plans without evidence. Optional applications that the ISO does
not ship are reported as not applicable and are not counted as passed.

When a plan was retried, the attempt with the highest number wins, even if it
failed. An older green attempt never hides a newer failure. Plans that were not
retried keep their last attempt.

## Local runs

`run-plan.sh` calls the finalizer from an `EXIT` trap, and writes HTML,
Markdown and JSON to `<results>/report/`. The executor's own exit status is
preserved; if the tests passed but the report failed, the run is not reported
as a success. `run-status.json` keeps the script's exit status apart from
`isotovideo`'s. To rebuild every format, including the PDF:

```sh
python3 openqa/report/finalize_report.py \
  --results-root /var/tmp/openqa/bios \
  --output-dir /var/tmp/openqa/bios/report --pdf
```

The trap is installed after the arguments are parsed and the repository is
located, so `--help` and usage errors produce no report.

## Sensitive data and limits

`run-status.json` holds identifiers and states only. It never contains step
outputs, tokens, the test password or runner transcripts. If redacting the
diagnostics fails, a plan publishes only its safe report, not the logs that may
still contain the password. The emergency summary records an exception's class,
not its message.

A plan's test budget is its job limit minus the time preparation already spent,
minus ten minutes reserved for collecting and publishing. The run report runs in
its own job, so it can report an artifact that a lost plan runner never uploaded.
No report is promised in these cases, and none of them yields a pass:

- the runner is lost entirely or runs out of disk;
- GitHub's artifact storage is unavailable;
- a cancellation stops the finalizers themselves.

## How it is tested

`openqa/report/test_report_finalization.py` covers success, module and
application failures, optional absences, missing `vars.json`, invalid JSON,
missing modules or plans, KVM and preparation failures, a failing HTML
generator, a missing PDF dependency, numeric attempt selection and secret
handling. It also runs the real script against a missing ISO.

The pull-request workflow publishes three synthetic result sets through
`openqa-report.yml`: success, a deliberate producer failure and an incomplete
run. It then downloads the reports and checks the PDF, HTML, Markdown and JSON.
None of this replaces running an ISO.

`runner.temp` exists in the steps' context, not in a job's `env`, so
runner-dependent paths are resolved in the first step and exported through
`GITHUB_ENV`.

References:
[`jobs.<job_id>.needs`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds),
[status check functions](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions),
[context availability](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability),
[upload-artifact](https://github.com/actions/upload-artifact).
