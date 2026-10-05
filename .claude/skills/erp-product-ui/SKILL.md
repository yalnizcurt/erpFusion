---
name: erp-product-ui
description: >-
  Maintain HighStudio product UI behavior, including the fixed shell, Home and
  Engineering Studio navigation, project resumption, approval and history controls,
  permission-aware actions, authenticated downloads and bounded artifact views.
  Use for product interaction or frontend architecture changes.
---

# ERP product UI

## Use and ownership

This skill owns this application's behavioral UI contracts. The existing
[frontend-design skill](../../../.agents/skills/frontend-design/SKILL.md) owns
visual/aesthetic decisions. Reuse the approved console and current tokens; this
skill does not prescribe a new visual identity or duplicate design advice.

## Critical rules

- Keep header, sidebar and bottom bar stable; contain scrolling inside content
  regions. Long JSON/code must not widen the page or hide navigation.
- Home is the project directory. Requirement upload, engineering stages, reviews,
  revisions/history and sandbox/release work belong in a resumable Studio.
- Display server-computed gate eligibility and current versus historical validity.
  Never allow a frontend-only approval or imply automatic progression unsupported
  by the backend.
- Use authoritative permissions for visible actions and preserve backend checks.
  Bind review/download actions to the exact selected eligible revision/candidate.
- Route requests/downloads through the authenticated API helpers. Keep sensitive
  drafts and tokens out of persistent browser storage and external services.

## Do not assume

The mock's local persistence/authentication represents product behavior. Hidden
buttons enforce access control. A historical APPROVED badge is a current gate.
A download is a qualified native installer. Every configured artifact uses an
Oracle-specific viewer. Leaving Studio cancels a committed generation job.

## Pattern architecture reference

Read the [HighStudio pattern architecture](../../../docs/architecture/highstudio-integration-patterns.md)
when a task changes pattern selection, approved baseline pins, target runtime or qualification
claims. Reuse existing intelligence, ownership, revision and evidence services; installation
is required only when the selected pattern contract requires it.

## Source entry points

- [App/navigation](../../../frontend/src/App.jsx),
  [fixed shell styles](../../../frontend/src/product.css), [base styles](../../../frontend/src/index.css).
- [Project directory](../../../frontend/src/components/ProjectDirectory.jsx),
  [Studio](../../../frontend/src/components/ProjectStudio.jsx),
  [requirements](../../../frontend/src/components/RequirementsWorkspace.jsx).
- [Review/artifact views](../../../frontend/src/components/BottomCards.jsx),
  [package view](../../../frontend/src/components/DeploymentPackageView.jsx),
  [sandbox](../../../frontend/src/components/SandboxWorkspace.jsx).
- [API helpers](../../../frontend/src/api.ts),
  [identity contracts](../../../frontend/src/contracts/identity.ts),
  [resource loading](../../../frontend/src/hooks/useApiResource.ts).

## Read as needed

- [Studio and fixed shell](references/studio-and-fixed-shell.md): navigation, mutations, downloads and privacy.
