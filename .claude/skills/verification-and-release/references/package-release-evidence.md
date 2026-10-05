# Package candidate, sandbox and release evidence

## Candidate contract

Read [packages.py](../../../../backend/app/services/packages.py), especially
`source_files`, `package_state`, `approved_test_plan`, `create_candidate` and
`current_release`; [package routes](../../../../backend/app/api/packages.py),
[engineering models](../../../../backend/app/models/engineering.py) and
[sandbox UI](../../../../frontend/src/components/SandboxWorkspace.jsx).

A candidate is an immutable source ZIP from current approved, validated configured
stage revisions. The manifest records file names/sizes/checksums, artifact/version
and input snapshot hashes, profile/input/workflow bindings, provenance and test
plan. File contracts may be configured; PL/SQL/SQL extraction also has legacy
compatibility handling. Reject path traversal, reserved names, collisions,
missing implementation content and stale approvals.

Individual downloads use the exact candidate bytes. Historical candidates/releases
stay bound to their original evidence and do not become current merely because
their historical status was approved. Preserve private authenticated downloads
and verify checksums; do not regenerate a file silently during download.

## Pattern qualification binding

Pattern-bound candidates and attempts retain the exact pattern contract and baseline versions.
Release eligibility follows that pattern's runtime, required capabilities, allowed modes,
assurance and test plan. Installation is optional where delivery is API/file/external/assisted.
A source checksum or declared runtime type cannot substitute for missing native evidence.

The execution worker can collect machine observations from installed adapters. The Publisher
simulator remains `SIMULATED`, while the real Publisher transport observes only existing-report
checks/runs. Native generated-candidate identity and installation remain unqualified. A native
release policy requiring those assurances must block incomplete remote/manual evidence.

## What the assisted sandbox flow establishes

The configured `testing` contract provides a version and uniquely identified
required cases with independent expected values. Evidence submission binds the
candidate checksum, reviewed source checksum, environment, connection configuration,
secret version and exact test-plan hash. The API compares entered case outcomes/
actual values against that plan; humans supply the observations.

Assisted records identify `ASSISTED_MANUAL`,
`assurance=authenticated_tester_attestation`, and
`remote_exact_bytes_verified=false`. Assisted evidence listing does not certify native import.
Use the separate attempt/adapter records for machine execution claims; preserve their
operation-specific assurance and simulation labels.

Sign-off requires an authorized tester/client authority and the eligible latest
passing evidence for the current candidate/connection/plan. It creates an immutable
release containing the candidate, test report and release manifest. Automatic
import remains unsupported. Do not relabel this as an independently verified ERP
installation or successful Oracle report execution.

## Changes and additional qualification

Input/profile/artifact changes invalidate current package eligibility while
preserving historical releases. Changes in environment/connection/secret/plan
bindings invalidate current sign-off evidence. Preserve all comparisons when
adding new release endpoints or UI actions.

Compilation needs exact-source compiler results. Native installation needs an
authorized adapter and target evidence. Execution needs an approved job and
collected outputs/logs. Remote verification must establish installed/executed
artifact identity and independent output assertions; typed observations alone
cannot provide it. Production readiness additionally needs applicable security,
recovery and operational qualification. For Fusion native limitations consult
[Oracle Fusion](../../erp-integrations/references/oracle-fusion.md).

[Package release tests](../../../../backend/tests/test_package_releases.py)
exercise bundle completeness, stale bindings, human sign-off and ownership with
synthetic fixtures. Their results do not certify native vendor import/execution.
