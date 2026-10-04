# Oracle Fusion: implemented boundaries

## Current connection path

Read [erp_connections.py](../../../../backend/app/services/erp_connections.py),
[connection routes](../../../../backend/app/api/connections.py) and
[contracts](../../../../backend/app/schemas/connections.py).

The configured adapter is currently `oracle_fusion_publisher`. It uses HTTPS SOAP
at `/xmlpserver/services/ExternalReportWSSService`, scoped username/password
credentials from Secrets Manager, and an approved `/Custom/...xdo` report path.
The operation contract currently admits PING and RUN_REPORT. This is a specific
Publisher protocol implementation, not a general Oracle installation adapter.

`probe_connection` checks network access and uses `hasReportAccess` for
authentication/report permission observations. Its response keeps tenant identity
and report execution unverified and import capability unsupported. A configured
`expected_tenant` string does not verify remote tenant identity. Probe evidence
is version-bound and expires.

`execute_report` implements bounded CSV `runReport` output with exact connection,
secret-version and report-path checks and output provenance. It exists as a
service helper and has synthetic protocol tests; the current Studio sandbox
flow does not wire it to an approved automatic execution job. Do not report the
helper as an end-to-end live sandbox feature.

## Generation and package target

[Strategy selection](../../../../backend/app/services/codegen/strategies.py)
contains Oracle-named compatibility strategies using compiled LLM context.
They do not import/install Publisher assets or demonstrate compilation.

Fusion SaaS does not provide an arbitrary customer PL/SQL package installation
target through this portal. A Fusion-native deliverable needs a qualified native
asset/build/import route, such as an approved Publisher report/data model.
Generated `.pks`/`.pkb` sources require a separately authorized compatible Oracle
database target. URL, username and password do not establish deployment permission.
The product decision is recorded in the
[sandbox plan](../../../../docs/product-ui-bedrock-and-oracle-sandbox-plan.md).

## Oracle assumptions outside the adapter boundary

Inspect these before touching generic orchestration or package contracts:

- [api/generation.py](../../../../backend/app/api/generation.py), `_run_validators`:
  an `oracle_attribute_lineage` branch explicitly retrieves FDD/TDD/SQL.
- [services/packages.py](../../../../backend/app/services/packages.py), `source_files`
  and `package_state`: PL/SQL/SQL compatibility fields and Oracle-lineage handling
  coexist with generic configured file contracts.
- [validation/engine.py](../../../../backend/app/services/validation/engine.py):
  Oracle SQL/PLSQL and attribute-lineage assumptions alongside common checks.
- [services/ai/](../../../../backend/app/services/ai/): legacy stage-specific prompt
  builders, including PL/SQL source handling, are separate from the active strategy path.
- [development fixtures](../../../../backend/app/cli/fixtures/development-v1.json):
  non-Oracle drafts inherit Oracle-shaped stage names.

These are compatibility/debt locations, not rules for future ERPs. Isolating them
requires a scoped application change; documentation does not itself refactor them.

## Evidence limits

[Package routes](../../../../backend/app/api/packages.py) currently record assisted
manual sandbox evidence and sign-off; they mark automatic import unsupported and
remote exact bytes unverified. A source ZIP or local validation PASS is not proof
of native installation or execution. A live demo requires an authorized tenant,
approved native baseline, permitted operations and independently checked outputs.
