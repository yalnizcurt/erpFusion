# Requirement clarification and design

## Source paths

Read [requirements routes](../../../../backend/app/api/requirements.py),
[bounded ingestion](../../../../backend/app/services/requirement_ingestion.py),
[RequirementsWorkspace](../../../../frontend/src/components/RequirementsWorkspace.jsx),
[WorkflowEngine](../../../../backend/app/services/workflow.py) and
[review routes](../../../../backend/app/api/reviews.py).

## Intake behavior

The product accepts PDF, DOCX, TXT and Markdown requirement documents through
the project's Studio. Uploads are size-bounded, scanned when configured, privately
stored and checksum-bound. Parsing happens in a bounded subprocess; macros,
unsafe archives/XML and unsupported documents are rejected. Image-only PDFs can
require OCR; OCR is not implemented. Development unscanned fixtures are distinct
from staging/production, which require a clean local scan.

Successful extracted text is added to the current requirement through
`revise_inputs`; document records retain extraction/scan state and requirement
version. A failed/quarantined document is not an accepted requirement revision.
Upload/context-edit requests use expected version guards. Do not bypass these
guards by directly assigning the project text in a new endpoint.

Uploaded document text and ERP references are source material. Their embedded
instructions cannot authorize actions or override workflow/security requirements.
Extraction does not prove requirement completeness or source correctness.

## Reviewable engineering sequence

The product intent is requirement clarification, FDD, TDD, then configured
implementation stages. Inspect the selected profile for the actual stage list
and output contract. An ERP may have separate SQL review or different files;
PKS/PKB are not universal stages.

`WorkflowEngine.review_blockers` recognizes unresolved assessment questions,
missing information, ambiguities and assumptions needing confirmation in current
and legacy content contracts. Preserve this server-side assessment gate; UI
warnings alone do not protect approval.

FDD should establish the approved functional interpretation and source/output
mapping. TDD should establish a reviewable implementation and test approach.
These are product requirements; current model output/static checks do not prove
that every requested design section or mapping is complete. Inspect configured
prompts and validators rather than inventing a universal hidden template.

## Revisions and human review

Validation success moves a generated draft through AI validation into pending
human review. Authorized human review approves, requests changes with comments,
or rejects the exact current eligible revision. Comments are preserved if the
submission fails in the UI; reviewer identity comes from authentication.

Approved stages unlock subsequent work. Current UI generation remains user
triggered; approval does not automatically launch the next stage. Returning to
an earlier point creates/revises current work and invalidates descendants. Keep
prior decisions visible as history without presenting them as current validity.

The [production plan](../../../../docs/production-implementation-plan.md) records
desired completeness and future workflows. It is not evidence those checks or
automated execution loops are already implemented.
