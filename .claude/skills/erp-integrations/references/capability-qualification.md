# ERP capability qualification

## Evaluate operations separately

For a requested ERP/edition/version/environment, identify the following evidence:

| Capability | What establishes it |
|---|---|
| ERP profile | Versioned registry entry and lifecycle state |
| Intelligence configuration | Published applicable prompts, relevant approved knowledge/packages and recorded versions |
| Validation support | Actual common/configured rules or installed validator; state what each checks |
| Package format support | Builder/extractor emits the complete required native file structure |
| Connection support | Implemented authenticated protocol for the allowed operation |
| Installation support | Qualified native import/deployment mechanism and permissions |
| Execution support | Approved installed artifact is run and its output/logs collected |
| Qualified/live support | Evidence binds the real target, operation, versions and tested artifact |
| Production qualification | Applicable runtime, security, recovery and operational release requirements demonstrated |

Do not collapse these into a single “ERP supported” Boolean. State partial support
and blockers explicitly. Ping is narrower than execution, and execution of an
existing report is narrower than installation of a generated candidate.

## Current repository evidence

- [Catalogue import](../../../../backend/app/cli/erp_catalogue.py) creates audited
  draft family data and preserves existing governed configuration. SAP, Workday,
  Dynamics and other names do not imply executable connectors.
- [Generic JSON generation](../../../../backend/app/services/codegen/strategies.py)
  can use newly configured intelligence without adding an ERP-name source branch.
  This establishes framework behavior, not vendor-native package execution.
- Oracle compatibility generation/validators and the Fusion Publisher protocol
  exist; their native import/Studio automatic execution qualification is incomplete.
- [Demo ERP browser acceptance](../../../../frontend/e2e-fullstack/onboarding.spec.ts)
  exercises UI-created configuration against the real API/compiler/worker with a
  mock model. It is not live ERP or full package-installation evidence.

## Onboarding work

1. Identify the exact product/edition, business operation, artifact format and target.
2. Determine which existing configured strategy and protocol operations cover it.
3. Configure approved prompts, knowledge, baselines, output contracts and validators
   through the governed registry; record missing native capabilities.
4. If deterministic behavior or a new native protocol is needed, implement and test
   that capability through the appropriate adapter boundary in an authorized task.
5. Qualify the exact candidate/operation in an authorized non-production environment,
   retaining independently checked outputs and provenance before making live claims.

Use [test evidence](../../verification-and-release/references/test-evidence.md) and
[release evidence](../../verification-and-release/references/package-release-evidence.md)
for reporting. Do not populate credentials, publish profiles or contact a vendor
merely because this procedure is present in a skill.
