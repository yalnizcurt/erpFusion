# Profile and intelligence contracts

## Authoritative entry points

Read [profile routes](../../../../backend/app/api/erp_profiles.py), especially
`_publication_stages`, `create_profile_version`, prompt/asset publication and
retirement. Read [profile models](../../../../backend/app/models/erp_profile.py),
[asset models](../../../../backend/app/models/erp_assets.py) and
[strategy selection](../../../../backend/app/services/codegen/strategies.py).
Inspect these symbols before changing a configuration shape; do not copy schemas
from dated plans as if they were implemented request contracts.

## Distinct resources

- `ERPProfile` is the ERP identity; `ERPProfileVersion` carries workflow,
  supported artifact types and configuration for a selectable version.
- `PromptVersion` is the active registry for GLOBAL, ERP and STAGE prompts.
  `ERPStagePrompt` remains a legacy model/table; its presence does not make it
  the compiler's prompt source.
- `ERPAssetVersion` represents PACKAGE or KNOWLEDGE resources, with logical
  asset identity, version, metadata, text context and separately stored bytes.
- Requests reference a profile ID and exact profile-version ID. Their selected
  client installation and execution environment are additional bindings.

## Publication and edits

Draft/review versions can be configured. Published/retired content cannot be
edited in place through the profile routes. Creating a profile version clones
the latest published configuration, prompt records and latest published assets
into a draft; do not treat cloned row IDs as the same version record.

Publication checks configured stage identifiers/order/dependencies, supported
types, installed strategy/validation adapter names, generation settings and
published applicable prompts. An ERP wildcard prompt can satisfy stage coverage.
These checks do not certify complete business designs, relevant baseline assets,
native builds or ERP execution. Inspect each route's preconditions when modifying
prompt/asset lifecycle; do not mutate a published profile through a child endpoint.

The workflow enforces serial progression in the configured stage-list order in
addition to declared dependencies. Stage names, output contracts, prompt stages,
review roles and adapters are data, not a universal Oracle sequence.

## Intelligence consumption

[PromptCompiler](../../../../backend/app/services/prompt_compiler.py) retrieves
published prompts for the pinned profile plus applicable global prompts and
bounded relevant assets/guidance. [Generation jobs](../../../../backend/app/api/generation.py)
freeze the resulting context at enqueue time. Changes to applicable global
prompts or reusable guidance can affect a later run even when the ERP profile
version is unchanged; run provenance and resolved context record what was used.
Do not promise that a profile ID alone freezes all intelligence forever.

## Existing compatibility cautions

The [development fixture](../../../../backend/app/cli/fixtures/development-v1.json)
gives some non-Oracle draft profiles Oracle-shaped implementation stage names.
The [22-family catalogue](../../../../backend/app/cli/fixtures/erp-catalogue-v1.json)
is an onboarding backlog, not a native-adapter inventory. Neither is a reason to
require PKS/PKB or SQL for a new ERP.

ERP administration still accepts several configuration bodies as dictionaries;
the UI has JSON configuration editors. Do not describe this as a complete typed
configuration designer or a fully frozen cross-registry publication manifest.
