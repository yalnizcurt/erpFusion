---
name: erp-engineering-lifecycle
description: Change or diagnose erpFusion requirement intake, clarification, FDD/TDD and configured implementation generation, approval gates, revisions, durable jobs, prompt compilation or scoped feedback. Use for workflow progression, regeneration, backtracking and history issues.
---

# ERP engineering lifecycle

## Use and ownership

Treat requirement, clarification, FDD, TDD, configured implementation/package
stages, validation and approval as one versioned lifecycle. This skill owns its
state transitions and generation context. ERP-specific capabilities, access
controls, UI presentation and sandbox release qualification have separate owners.

## Critical rules

- Stage order/dependencies come from the pinned profile. Every downstream stage
  needs currently valid upstream human approval; historical APPROVED text alone
  cannot unlock it.
- Approve the exact current revision and inputs. Resolve blocking requirement
  questions/assumptions before approving the assessment.
- Reuse shared revision/invalidation and workflow paths. Regeneration/backtracking
  invalidates active descendants and stale jobs while retaining earlier content,
  decisions, inputs, runs and historical downloads.
- Freeze compiled context before enqueueing a durable run. Claims, authorization
  and completion checks must prevent duplicate/stale work from replacing new work.
- Retrieve relevant approved guidance by scope. Human approval is required to
  promote project feedback into reusable ERP/global guidance.

## Do not assume

Approval queues the next generation automatically. The worker is an autonomous
agent swarm. A regeneration must reproduce identical model output. Sandbox
failures automatically become verified learning notes. Legacy AI helper names
identify the active generation implementation.

## Source entry points

- [WorkflowEngine](../../../backend/app/services/workflow.py),
  [input revisions](../../../backend/app/services/project_revisions.py).
- [Generation API/worker execution](../../../backend/app/api/generation.py),
  [worker CLI](../../../backend/app/cli/generation_worker.py).
- [PromptCompiler](../../../backend/app/services/prompt_compiler.py),
  [strategy dispatch](../../../backend/app/services/codegen/strategies.py).
- [Requirement routes](../../../backend/app/api/requirements.py),
  [reviews](../../../backend/app/api/reviews.py), [feedback](../../../backend/app/api/feedback.py).

## Read as needed

- [Requirements and design](references/requirements-and-design.md): intake and approval content.
- [Revisions and jobs](references/revisions-and-jobs.md): state, concurrency and history.
- [Prompts and feedback](references/prompts-and-feedback.md): active generation and provenance.
