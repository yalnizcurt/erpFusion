# Credentials and approved data boundaries

## ERP credentials and connections

Read [connection routes](../../../../backend/app/api/connections.py),
[secret/transport service](../../../../backend/app/services/erp_connections.py),
[connection contracts](../../../../backend/app/schemas/connections.py) and
[connection models](../../../../backend/app/models/connection.py).

Username/password inputs are write-only `SecretStr` values. The service writes
Secrets Manager values; database rows hold only secret reference/version and
non-secret connection metadata. Reads validate expected secret prefix and
client/installation/environment/operation tags, and require the pinned version
to remain current. Changing credentials/configuration invalidates earlier
connection evidence; do not bypass scope/version checks by fetching arbitrary
secret ARNs.

Transport validates exact globally approved plus connection-approved hosts before
secret/network access, requires HTTPS/443, rejects redirects/proxy routing and
non-public DNS destinations, and pins the approved resolved IP while retaining
hostname TLS verification. Responses, XML and timeouts are bounded. Never disable
TLS, allow metadata/private destinations or expose vendor fault bodies to make a
demo pass. Customer-network connectivity is future architecture, not permission
to relax this installed adapter's restrictions.

Credentials never belong in prompts, model context, requirement/schema JSON,
knowledge assets, generated documents, logs or browser storage. Do not use real
customer secrets as fixtures or print environment/SDK responses during debugging.

## Private files and content

[artifact_storage.py](../../../../backend/app/services/artifact_storage.py) supports
restricted local files and configured private S3 storage using the SDK credential
chain. S3/private storage capability is implemented; any live deployment's IAM,
bucket, encryption and retention configuration still needs verification.

Authorize ownership before reading a storage reference. Preserve path/bucket
containment, exclusive writes, bounds and checksum verification in requirement/
candidate/release download routes. Do not replace authenticated downloads with
public object URLs. Production requirement documents need a clean configured local
scan; development unscanned fixtures do not qualify production ingestion.

Compiled prompts, requirement text and generated artifacts are content-bearing
engineering records with controlled access. Safe provider receipts/audit metadata
and ordinary logs are different data classes. Do not expose provider reasoning
or hidden chain-of-thought as generation provenance.

## Providers, destinations and logs

[Settings](../../../../backend/app/config.py),
[provider factory](../../../../backend/app/services/llm/factory.py) and
[Bedrock provider](../../../../backend/app/services/llm/bedrock.py) enforce the
current deployed provider policy: approved regional Bedrock with workload IAM,
configured private endpoint and retention/residency attestations. Attestation
flags do not themselves configure AWS policy or prove account qualification.
Groq is explicitly authorized for local synthetic work; mock mode requires
explicit development/test configuration and is not a missing-key fallback.

No unauthorized external analytics, crash uploads, model providers, document
services, fonts/CDNs or generation-time browsing with customer context should
be introduced. External vendor knowledge acquisition needs its own approved
administrative workflow. An ERP destination remains operation-scoped.

[Logging](../../../../backend/app/core/logging.py) minimizes content, redacts
credentials and suppresses SDK/debug/exception bodies. Keep governed internal
audit and minimal operational records; “no telemetry” does not mean deleting
security evidence. Review the [security register](../../../../docs/security/verification-register.md)
and [data-boundary decisions](../../../../docs/product-ui-bedrock-and-oracle-sandbox-plan.md)
without treating their dated evidence as current certification.
