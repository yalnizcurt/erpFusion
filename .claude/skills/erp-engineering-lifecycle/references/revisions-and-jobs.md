# Revision validity, durable jobs and history

## Sources and bindings

Read [WorkflowEngine](../../../../backend/app/services/workflow.py), especially
`configured_stage_map`, `current_bindings`, `approve`, `invalidate_downstream`
and `invalidate_all`; [project_revisions.py](../../../../backend/app/services/project_revisions.py),
[generation.py](../../../../backend/app/api/generation.py),
[generation_worker.py](../../../../backend/app/cli/generation_worker.py), and
[artifact/input/run models](../../../../backend/app/models/engineering.py).
Artifact content/version metadata also live in
[version.py](../../../../backend/app/models/version.py) and
[erp_assets.py](../../../../backend/app/models/erp_assets.py).

Current bindings include profile-version ID, requirement version, schema/context
version and transitive approved upstream artifact-version IDs. Runs additionally
bind workflow revision, artifact ID and its previous current version. Gate
validity must be computed from current bindings, not a historical approval label.

## State and edits

- `configured_stage_map` adds the preceding configured stage as a dependency,
  enforcing serial order even where declared dependencies branch.
- Successful generation creates a new draft; validation success reaches
  `PENDING_HUMAN_REVIEW`/`PENDING_REVIEW`. Failure blocks progression.
- Approval requires the current pending revision, matching inputs and valid
  upstream dependencies. Concurrent/stale review must return conflict.
- `revise_inputs` locks the project, checks expected input versions, snapshots
  previous/current inputs and invalidates active work. Explicit profile upgrades
  use this path; silently adopting a newly published version is prohibited.
- Regeneration and request changes invalidate affected descendants and mark
  queued/running affected jobs stale. Earlier versions, approval decisions,
  provenance, input snapshots and immutable downloads remain historical.

Normal workflow reads calculate effective status without repairing stored gates
or creating audits. Do not call reconciliation/seed/repair functions from read
endpoints to make a screen appear consistent.

## Active job path

1. `trigger_generation` authorizes the project, locks/checks eligibility, compiles
   approved inputs and creates a QUEUED `GenerationRun` in the API transaction.
2. The separate CLI worker selects committed work within its client scope.
3. `process_generation_run` atomically claims QUEUED work and commits before the
   external model invocation. It uses stored resolved context and strategy dispatch.
4. Completion rechecks authorization, archive state, workflow revision, input
   bindings, artifact gate and previous version before attaching new content.
   Late results cannot replace newer work or approve/unlock descendants.
5. Effective requests, safe receipts, output/failure state and completion metadata
   are retained. Interrupted jobs become explicit failures; they are not blindly
   reinvoked. Recovery must release only the generation slot the old run owns.

The current worker polls the database. It is not the planned cloud queue/outbox
architecture, and no automatic next-stage/repair/retest loop is established.

## Verification anchors

Review [workflow tests](../../../../backend/tests/test_workflow.py),
[job tests](../../../../backend/tests/test_generation_jobs.py),
[worker recovery](../../../../backend/tests/test_worker_recovery.py) and
[upload revisions](../../../../backend/tests/test_requirement_uploads.py).
SQLite exercises logic but does not establish PostgreSQL lock/concurrency behavior.
Preserve these distinctions when modifying or reporting the workflow.
