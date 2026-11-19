# Handoff — email notifications for Icechunker automation

Status: implementation plan approved by the user on 2026-11-19; not implemented.

## Goal and scope

Add best-effort email alerts for failures in scheduled Icechunker automation jobs. Manual
`sync` and `verify` runs should not send email by default. Do not add alerts to scripts intended
for one-off/manual use.

`icechunker sync` includes the ROMS forecast and WW3 Icechunk store updates. In
`ops/pipeline.py`, it plans changes with `best_series_update.plan_changes` and commits with
`best_series_update.apply_update`. This is a separate orchestration path from the standalone
`stores/{roms_hiig,ww3_hawaii}/update_store.py` CLIs.

## Approved behavior

- Add an explicit `--notify` option, disabled by default.
- Have `icechunker cron` include `--notify` in its generated `sync` and weekly
  `verify --scope full` commands. Regular manual commands remain silent unless the option is
  explicitly supplied.
- Send one aggregated notification from the parent job runner after all selected datasets
  finish, not from `pipeline.process` or each worker. Report action/scope, failed dataset names,
  failure/timeout status, and relevant log paths.
- Send nothing for successful, idle/no-op, or dry-run jobs. Decide and test the treatment of
  expected lock-contention skips separately; avoid treating normal skips as operational
  failures.
- Delivery is best-effort: SMTP/configuration failure must not change the job exit status,
  failure records, pending transactions, or retry behavior.
- Keep secrets and potentially credential-bearing raw SDK/subprocess exception details out of
  email and logs. Include useful safe context and log paths instead.

## Relevant current architecture

- `ops/cli.py`: command parser and dispatch. `sync` supports `--config`, `--dataset`, and
  `--dry-run`; `verify` supports `--config`, `--dataset`, and `--scope`.
- `ops/jobs.py`: `cron_block()` emits suggested cron entries. `run()` starts one bounded worker
  process per selected dataset, records timeouts, aggregates nonzero results, and returns a
  nonzero status if any dataset failed. `worker()` writes per-dataset logs and durable
  `last-failure-*` records while deliberately limiting error details.
- `ops/pipeline.py`: per-dataset sync/verify implementation, including the Icechunk update.
- `ops/package.py`: explicit runtime payload allowlist. New runtime modules must be added there;
  development tests are not shipped.
- `ops/README.md` and `ops/config.example.toml`: operator instructions, generated scheduling,
  and existing `MAILTO` guidance. Update these to document notification setup and behavior.
- `stores/best_series_update.py`: also contains the standalone updater `main()`, current
  `--no-email` option, and updater notification calls. The automation pipeline calls shared
  update functions directly; it does not call `main()`.
- `stores/email_notifications.py`: current stdlib SMTP sender and best-effort wrapper, used by
  standalone updaters only. It is not in the Icechunker runtime package.
- `stores/README.md`: currently documents standalone updater email behavior and should be
  corrected if those hooks are removed.

## Implementation outline

1. Move or adapt the SMTP helper into `ops/` and add it to the explicit runtime manifest.
   Preserve the existing environment-based SMTP settings where appropriate:
   `PACIOOS_ALERT_EMAIL_TO`, `PACIOOS_ALERT_EMAIL_FROM`, `PACIOOS_SMTP_HOST`,
   `PACIOOS_SMTP_PORT`, `PACIOOS_SMTP_SECURITY`, `PACIOOS_SMTP_USERNAME`, and
   `PACIOOS_SMTP_PASSWORD`. Never put values in cron lines or committed config/examples.
2. Add `--notify` to the public `sync` and `verify` CLI options and include it in `cron_block()`.
   Keep worker invocations from sending alerts; the parent process owns notification delivery.
3. Aggregate failures and timeouts in `jobs.run()` and send one message after all selected jobs
   complete. Cover errors before worker launch if feasible without changing existing setup-error
   behavior. Preserve the existing return code and durable state even if sending fails.
4. Remove standalone-updater email calls and `--no-email` behavior if they are no longer needed.
   Keep the shared update functions usable by both paths. Remove or relocate obsolete helper
   docs/tests accordingly.
5. Test default manual silence, cron opt-in, multi-dataset aggregation, timeout reporting,
   expected skips/no-op behavior, SMTP failure isolation, secret-safe message content, and
   runtime packaging. Update `ops/README.md`, `ops/config.example.toml` only if configuration
   changes are needed, and `stores/README.md` if standalone behavior changes.

## Validation

Use the existing operations test command:

```bash
PYTHONPATH=ops:upload python -m unittest discover -s ops -p 'test_*.py'
```

Also run package/manifest tests, relevant Python compilation, `bash -n ops/icechunker`, and
`git diff --check`. Do not deploy, configure real cron, or send a real email as part of local
validation; mock SMTP.

## Session/worktree note

At handoff creation, branch is `notify-on-error`. `.envrc` and
`stores/test_email_notifications.py` are untracked; leave them untouched and do not stage them
without explicit direction. The test file was intentionally kept out of earlier commits.

Read `AGENTS.md`, `agent/handoff.md`, and `docs/design/deployable-icechunker.md` before
implementation; the latter records approved packaging and deployment constraints.
