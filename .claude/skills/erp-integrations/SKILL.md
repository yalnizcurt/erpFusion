---
name: erp-integrations
description: Change or assess HighStudio ERP profiles, prompts and assets, implementation adapters, connections, and vendor capability qualification. Use when onboarding an ERP or changing what an ERP integration can generate, validate, connect to, install or execute.
---

# ERP integrations

## Use and ownership

Use for ERP onboarding, profile/intelligence publication, adapter contracts,
connection behavior and capability claims. This skill owns ERP-specific behavior;
the engineering lifecycle owns approvals and jobs, security owns access/data
boundaries, and verification owns release evidence.

## Critical rules

- ERP catalogue/configuration does not establish executable integration support.
  Identify each required operation and its actual implementation/evidence.
- Resolve behavior through the request's pinned profile and configured installed
  adapters. Do not add ERP-name branches to generic workflow or fallback Oracle
  intelligence when a configured profile is incomplete.
- Keep profile, prompt/knowledge/package assets, validator, file format, connection,
  installation, execution and production qualification as separate capabilities.
- Published profile intelligence is changed through a new draft profile version.
  Existing requests upgrade explicitly; preserve their earlier evidence.
- Special deterministic/native behavior requires a real adapter. Generic JSON
  generation and a package extension cannot manufacture that capability.

## Do not assume

SAP, Workday, Dynamics and other catalogue families have live connectors. Fusion
Publisher access permits package installation. Oracle PL/SQL is a Fusion SaaS
installer. An existing compatibility branch is an architecture pattern to copy.

## Pattern architecture reference

Read the [HighStudio pattern architecture](../../../docs/architecture/highstudio-integration-patterns.md)
when a task changes pattern selection, approved baseline pins, target runtime or qualification
claims. Reuse existing intelligence, ownership, revision and evidence services; installation
is required only when the selected pattern contract requires it.

## Source entry points

- [Profile routes](../../../backend/app/api/erp_profiles.py): publication and cloning.
- [Profile models](../../../backend/app/models/erp_profile.py) and
  [intelligence/run models](../../../backend/app/models/erp_assets.py).
- [Generation strategies](../../../backend/app/services/codegen/strategies.py),
  [validation adapters](../../../backend/app/services/validation/strategies.py).
- [Connection service](../../../backend/app/services/erp_connections.py),
  [connection contracts](../../../backend/app/schemas/connections.py).
- [Catalogue importer](../../../backend/app/cli/erp_catalogue.py) and its fixtures.

## Read as needed

- [Profile contracts](references/profile-contracts.md): configuring/publishing intelligence.
- [Oracle Fusion](references/oracle-fusion.md): actual protocol and compatibility leaks.
- [Capability qualification](references/capability-qualification.md): onboarding or reporting support.
