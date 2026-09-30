# AI ERP Integration Engineering Agent

## 1. Overview

Build an AI-powered ERP Integration Engineering Agent that converts business integration requirements and ERP schema/context into a complete, reviewable, version-controlled integration engineering package.

The system is intended to reduce the manual effort involved in designing and implementing ERP data extraction/integration solutions while preserving human control over every important engineering decision.

The system must not behave as an unrestricted autonomous coding agent.

The intended operating model is:

```text
Input
  ↓
AI Analysis
  ↓
AI Generated Artifact
  ↓
Automated Validation
  ↓
HUMAN REVIEW / APPROVAL
  ↓
Next Stage
```

No downstream stage may proceed until the required human approval has been explicitly recorded.

The initial use case is the generation of ERP extraction solutions involving business entities, relational mappings, incremental extraction, data transformation/sanitization, flat-file generation, and PL/SQL packages. The architecture should be designed so that additional ERP systems and integration patterns can be added later without redesigning the entire platform.

---

# 2. Business Problem

Enterprise ERP systems contain large amounts of business-critical master and transactional data.

A single business entity is often distributed across multiple related entities, tables, attributes, configurations, physical locations, accounts, sites, and communication structures.

When another enterprise system requires this information, integration engineers must manually perform several activities:

1. Understand the business requirement.
2. Understand the ERP data model.
3. Identify relevant entities and attributes.
4. Determine relationships and join paths.
5. Map business attributes to source fields.
6. Define extraction rules.
7. Design full and incremental extraction logic.
8. Define filtering and transformation rules.
9. Create Functional Design Documents.
10. Create Technical Design Documents.
11. Write SQL.
12. Write PL/SQL packages.
13. Implement file formatting and data sanitization.
14. Validate that documentation and implementation remain consistent.
15. Package the solution for deployment.

This process is repetitive and highly dependent on experienced engineers.

The same type of engineering work is repeatedly recreated for different integration requirements.

This creates several problems:

* High development effort.
* Long turnaround time.
* Dependency on individual ERP/integration experts.
* Inconsistent document quality.
* Inconsistency between FDD, TDD and implementation.
* Incorrect or incomplete source-to-target mappings.
* Incorrect joins.
* Missing edge-case handling.
* Unsafe flat-file output.
* Incorrect incremental extraction logic.
* Difficult review and audit.
* Difficulty maintaining generated solutions when requirements change.

The objective of this system is to automate a significant portion of this engineering process while retaining explicit human ownership of the resulting design and code.

---

# 3. Core Problem Statement

The system must provide a controlled AI workflow that accepts:

* Business requirements.
* ERP schema information.
* Entity descriptions.
* Attribute definitions.
* Relationship information.
* Extraction requirements.
* FDD template.
* TDD template.

and produces:

* Functional Design Document (FDD).
* Technical Design Document (TDD).
* SQL extraction design/query.
* PL/SQL Package Specification (`.pks`).
* PL/SQL Package Body (`.pkb`).
* Validation results.
* Versioned engineering artifacts.
* Deployment/install manifest.

The system must ensure that generated artifacts remain traceable to their source requirements and approved design decisions.

---

# 4. Primary Objective

Create an AI-assisted ERP engineering platform that can take an integration requirement and systematically transform it into production-oriented engineering artifacts.

The platform should make the following workflow possible:

```text
Business Requirement
        +
ERP Schema / Context
        +
FDD Template
        +
TDD Template
        ↓
Context Analysis
        ↓
Entity / Relationship Understanding
        ↓
Functional Design
        ↓
Human Approval
        ↓
Technical Design
        ↓
Human Approval
        ↓
SQL Design
        ↓
Human Approval
        ↓
PL/SQL Generation
        ↓
Automated Validation
        ↓
Human Approval
        ↓
Deployment Package
```

---

# 5. Human-in-the-Loop Is a Mandatory Requirement

Human review is a fundamental system requirement, not an optional feature.

The AI must never have unrestricted authority to move from one engineering stage to the next.

For every major AI-generated artifact:

```text
AI generates
    ↓
AI validates
    ↓
Human reviews
    ↓
Human explicitly approves
    ↓
Next stage becomes available
```

Automated validation must never be considered equivalent to human approval.

## 5.1 Required Review Gates

At minimum, the system must provide review gates after:

### Gate 1 — Context Analysis

Human reviews:

* Identified entities.
* Relationships.
* Assumptions.
* Business interpretation.
* Ambiguities.
* Missing information.

### Gate 2 — FDD

Human reviews:

* Business scope.
* Attribute mappings.
* Extraction modes.
* Business rules.
* Sanitization requirements.

### Gate 3 — TDD

Human reviews:

* Technical architecture.
* Join design.
* SQL design.
* Parameters.
* Error handling.
* Incremental strategy.

### Gate 4 — SQL

Human reviews:

* SELECT list.
* Joins.
* Filters.
* Transformations.
* Performance considerations.

### Gate 5 — PL/SQL

Human reviews:

* Package specification.
* Package body.
* Procedure signatures.
* SQL implementation.
* File generation.
* Error handling.
* Watermark handling.

### Gate 6 — Final Validation / Release

Human reviews the complete package before it becomes deployment-ready.

---

# 6. Approval State Model

Every generated artifact must have an explicit lifecycle.

Minimum states:

```text
DRAFT
  ↓
AI_VALIDATED
  ↓
PENDING_HUMAN_REVIEW
  ↓
APPROVED
```

Alternative outcomes:

```text
PENDING_HUMAN_REVIEW
        ↓
REQUEST_CHANGES
        ↓
AI_REGENERATES
        ↓
PENDING_HUMAN_REVIEW
```

or:

```text
PENDING_HUMAN_REVIEW
        ↓
REJECTED
```

The system must prevent downstream execution when the required artifact is not approved.

An approved artifact must not be silently overwritten.

---

# 7. Input Model

The platform must support a project containing the following inputs.

## 7.1 Business Requirement

The business requirement describes what data is required, why it is required, extraction behavior, business rules, filters, and output expectations.

The system should not assume that the requirement follows a fixed structure.

The agent must interpret the requirement and identify:

* Business objective.
* Required entities.
* Required attributes.
* Extraction frequency/mode.
* Required filters.
* Required transformations.
* Output expectations.
* Business constraints.

---

## 7.2 ERP Schema / Context

The system will receive schema/context information describing the relevant ERP data model.

The context may contain:

* Entity names.
* Table names.
* Column names.
* Data types.
* Descriptions.
* Primary keys.
* Foreign keys.
* Relationships.
* Business meanings.
* Attribute descriptions.
* Sample metadata where available.

The agent must use only the supplied context when determining source mappings.

### Critical rule

The agent must never invent:

* Tables.
* Columns.
* Relationships.
* Foreign keys.
* Business attributes.
* ERP modules.
* Join conditions.

If the available context is insufficient to establish a required relationship or mapping, the system must identify the ambiguity and request human resolution instead of guessing.

---

# 8. FDD Template Requirement

The FDD will be provided as a Google Workspace / Google Docs template link.

The system must treat that document as the formatting and structural source of truth.

The original template must never be modified.

The system must create a new document based on the supplied template and populate the required content.

The generated document should preserve, wherever applicable:

* Fonts.
* Font sizes.
* Colors.
* Heading styles.
* Paragraph spacing.
* Line spacing.
* Tables.
* Table formatting.
* Headers.
* Footers.
* Numbering.
* Page structure.
* Existing document layout.

The AI should determine the business content.

A document-generation component should be responsible for applying that content to the template.

The design must therefore separate:

```text
AI Content Generation
        ↓
Structured FDD Representation
        ↓
Document Generation
        ↓
New Google Docs Document
```

The original template remains unchanged.

---

# 9. TDD Template Requirement

The TDD will also be supplied through a Google Workspace / Google Docs template link.

The same template-driven approach must be followed.

The system must:

1. Access the supplied template.
2. Create a new copy.
3. Populate the appropriate sections.
4. Preserve the template's formatting and structure.
5. Save the generated TDD as a separate versioned artifact.
6. Maintain its relationship to the corresponding FDD and requirement version.

---

# 10. Functional Design Document Requirements

The generated FDD should contain, at minimum, the information required to explain the business-level extraction design.

The exact structure must follow the supplied FDD template.

The generated content should cover:

## Business Scope

Describe:

* Business purpose.
* Scope of the extraction.
* Relevant entities.
* Intended downstream use.

## Business Attribute Mapping

Every required business attribute must be mapped to:

* Business attribute.
* Source entity/table.
* Source column.
* Business description.
* Transformation/derivation, if applicable.
* Relevant business rules.

## Extraction Modes

The initial design must support three conceptual modes:

### FULL

Extract all records satisfying the applicable business criteria up to the current extraction point.

### DELTA

Extract records created or modified within the defined incremental window using the appropriate modification timestamp.

### SELECTIVE

Extract records according to explicit runtime filtering parameters.

The exact implementation must be determined from the supplied requirement and schema.

## Data Sanitization

Text output must be protected from breaking downstream flat-file structure.

At minimum, the design must account for:

* Carriage return.
* Line feed.
* Reserved delimiter characters.
* NULL values.
* Data type conversions.

The exact treatment of reserved characters must be explicitly documented rather than assumed.

---

# 11. Technical Design Document Requirements

The TDD must translate the approved FDD into an implementation-oriented design.

At minimum, it must describe:

* Technical architecture.
* Source entities.
* Entity relationships.
* Join strategy.
* SQL design.
* Input parameters.
* Output structure.
* Extraction modes.
* Incremental logic.
* Data sanitization.
* File generation.
* Logging.
* Exception handling.
* Performance considerations.
* Restart/recovery behavior.
* Deployment considerations.

The TDD must remain traceable to the approved FDD.

---

# 12. SQL Generation

The system must generate the SQL required for the approved extraction design.

The SQL must be derived from:

1. Approved schema/context.
2. Approved business mapping.
3. Approved FDD.
4. Approved TDD.

The generated SQL must not introduce information not present in the approved design.

The system should validate:

* Table existence.
* Column existence.
* Join-key availability.
* Join consistency.
* Required filters.
* Required output attributes.
* Data types.
* Alias consistency.
* Incremental predicates.
* Runtime parameters.

---

# 13. PL/SQL Package Generation

The system must generate executable PL/SQL artifacts based on the approved technical design.

Two separate source files must be produced:

```text
<package_name>.pks
<package_name>.pkb
```

## 13.1 Package Specification

The package specification must contain the required public interfaces defined by the approved TDD.

The package should support the required extraction modes, runtime parameters, and output configuration.

The exact interface must be derived from the approved design rather than hardcoded globally.

---

# 14. Package Body

The package body must contain the complete implementation.

It may include:

* Cursor definitions.
* SQL extraction logic.
* Runtime filtering.
* Incremental logic.
* Data sanitization.
* File creation.
* Record formatting.
* Logging.
* Exception handling.
* Watermark handling.

The generated code must be complete.

The system must not generate:

```text
TODO
TBD
CODE GOES HERE
IMPLEMENT LATER
PSEUDOCODE
```

or equivalent placeholders in a package marked for review.

---

# 15. Data Sanitization

All textual values written to a delimiter-based output must be processed according to the approved sanitization rules.

The system must identify every textual expression participating in the output payload and verify that the required sanitization has been applied.

The initial implementation should support removal or transformation of:

```text
CHR(10)
CHR(13)
|
```

according to the approved business rule.

The implementation must also handle NULL values consistently.

The validator must flag any output text field that bypasses the approved sanitization mechanism.

---

# 16. Incremental Extraction and Watermark Management

Incremental extraction must be designed to avoid repeatedly processing historical data.

The system must support a concept of an extraction watermark/token.

The design must define:

* Previous successful extraction timestamp.
* Current extraction boundary.
* Selection predicate.
* Successful completion behavior.
* Failure behavior.
* Retry behavior.

The watermark must only advance after the extraction has completed successfully according to the system's defined success criteria.

A failure must not incorrectly advance the watermark.

The implementation must be restartable and auditable.

---

# 17. File Generation

The generated integration package may need to produce delimiter-based flat files.

The system must define:

* File name.
* File format.
* Delimiter.
* Column order.
* Header behavior.
* NULL representation.
* Character sanitization.
* Date/time formatting.
* Number formatting.
* Record termination.
* Error behavior.

The exact output contract must come from the approved requirement/design.

---

# 18. Validation Engine

The system must perform automated validation before presenting an artifact for human approval.

Validation should include multiple categories.

## Schema Validation

Verify:

* Tables/entities exist in supplied context.
* Columns exist.
* Data types are understood.
* Relationships are supported.

## Mapping Validation

Verify:

```text
Requirement
    ↔ FDD
    ↔ TDD
    ↔ SQL
    ↔ PL/SQL
```

Required business attributes must not disappear between stages.

## SQL Validation

Check:

* Referenced objects.
* Joins.
* Filters.
* Parameter usage.
* Output fields.

## PL/SQL Validation

Check:

* Package specification/body consistency.
* Procedure signatures.
* SQL integration.
* Error handling.
* Sanitization.
* Required modes.
* File handling.
* Watermark logic.

## Document Validation

Check:

* Required sections exist.
* Required mappings are populated.
* Generated content is present.
* Template structure is retained.

## Cross-Artifact Validation

The system must detect inconsistencies such as:

```text
FDD includes attribute
        ↓
TDD omits attribute
        ↓
SQL omits attribute
```

or:

```text
TDD specifies parameter
        ↓
PKS does not expose parameter
```

or:

```text
SQL output contains unsanitized text
```

---

# 19. Versioning

Every generated artifact must be versioned.

Example:

```text
Project
│
├── Requirement v1
│
├── FDD
│   ├── v1
│   └── v2
│
├── TDD
│   ├── v1
│   └── v2
│
├── SQL
│   ├── v1
│   └── v2
│
└── PL/SQL
    ├── v1
    └── v2
```

Approved artifacts must remain immutable.

When an approved artifact is changed, a new version must be produced.

---

# 20. Dependency Invalidation

Artifacts form a dependency graph.

For example:

```text
Requirement
    ↓
Context Analysis
    ↓
FDD
    ↓
TDD
    ↓
SQL
    ↓
PL/SQL
    ↓
Deployment
```

If an upstream approved artifact changes, dependent artifacts may become invalid.

Example:

```text
FDD v1 APPROVED
        ↓
TDD v1 APPROVED
        ↓
PKB v1 APPROVED

FDD changes
        ↓
TDD = INVALIDATED
SQL = INVALIDATED
PKS = INVALIDATED
PKB = INVALIDATED
```

The system must not allow stale downstream artifacts to remain incorrectly marked as current/approved.

---

# 21. Auditability

The platform must retain a traceable history of the engineering process.

For each artifact, record at minimum:

* Project identifier.
* Requirement version.
* Artifact type.
* Artifact version.
* Generation timestamp.
* AI model/agent version where available.
* Input context version.
* Validation result.
* Human reviewer.
* Review timestamp.
* Review decision.
* Human comments.
* Version relationship.
* Approval state.

The purpose is to make it possible to understand:

```text
Why was this artifact generated?
What requirement produced it?
What schema/context was used?
What changed between versions?
Who approved it?
When was it approved?
```

---

# 22. Human Comments and Regeneration

A reviewer must be able to request changes.

Example:

```text
Human:
"Customer status must be derived from the approved status mapping."

        ↓

AI analyzes requested change
        ↓
Updated FDD
        ↓
AI validation
        ↓
Human review again
```

The AI must preserve the original version and create a new version.

Human comments should become part of the audit history.

---

# 23. Separation of Responsibilities

The platform must clearly separate the roles of AI, automated validation, and human approval.

## AI Responsibilities

AI may:

* Analyze requirements.
* Analyze schema/context.
* Identify relationships.
* Generate design content.
* Generate SQL.
* Generate PL/SQL.
* Identify ambiguities.
* Perform reasoning.
* Propose transformations.
* Explain generated artifacts.

## Automated Validation Responsibilities

Validation may:

* Check schema references.
* Check mappings.
* Check document structure.
* Check consistency.
* Check code structure.
* Check required implementation rules.

## Human Responsibilities

The human must:

* Review business interpretation.
* Resolve ambiguities.
* Approve mappings.
* Approve technical architecture.
* Approve generated code.
* Approve release readiness.

The system must not blur these responsibilities.

---

# 24. Safety and Non-Hallucination Rules

The following are mandatory.

### Rule 1 — No Invented Schema

Never create a table, column, key, relationship, or attribute that is not supported by the provided context.

### Rule 2 — No Silent Assumptions

Material assumptions must be surfaced to the human reviewer.

### Rule 3 — No Self-Approval

AI validation cannot approve an artifact.

### Rule 4 — No Skipped Gates

A downstream artifact cannot be approved if its required predecessor is not approved.

### Rule 5 — No Silent Overwrites

Approved artifacts cannot be modified in place.

### Rule 6 — No Fake Execution Claims

The system must distinguish between:

* Generated code.
* Validated code.
* Human-approved code.
* Executed code.
* Deployed code.

Generating a package does not mean it was executed successfully.

### Rule 7 — No Placeholder Production Code

A package presented for final review must contain complete implementation unless an explicit human decision marks an unresolved item.

---

# 25. Document Generation Principles

The platform must separate semantic generation from document formatting.

Conceptually:

```text
AI
 ↓
Structured Artifact Model
 ↓
Document Renderer
 ↓
Google Docs Copy
```

The AI should not be responsible for reproducing fonts, spacing, colors, or layout through free-form text generation.

The supplied Google Docs template is the visual source of truth.

The document generation layer should preserve the template's formatting while updating its content.

---

# 26. Code Generation Principles

Code generation must also be separated from business reasoning.

Conceptually:

```text
Approved FDD
      ↓
Approved TDD
      ↓
Approved Extraction Model
      ↓
Code Generator
      ↓
SQL
      ↓
PKS / PKB
```

The code generator should consume structured, approved design information instead of independently reinterpreting the original business requirement whenever possible.

This is intended to minimize divergence between design and implementation.

---

# 27. Project-Level Traceability

Every generated artifact should be linked to its source artifacts.

Example:

```text
Requirement R001
      ↓
Context C001
      ↓
FDD F001 v2
      ↓
TDD T001 v2
      ↓
SQL S001 v2
      ↓
PKS P001 v2
      ↓
PKB P002 v2
      ↓
Release REL001
```

A reviewer should be able to navigate from the final package back to the original business requirement and schema context.

---

# 28. Deployment Readiness

The system may generate a deployment package containing relevant approved artifacts, such as:

```text
deployment/
├── <package>.pks
├── <package>.pkb
├── install.sql
├── rollback.sql
├── manifest
└── documentation
```

The exact contents are determined by the approved implementation and deployment requirements.

The system must not represent a package as deployment-ready until:

* Required artifacts exist.
* Automated validation has passed.
* Required human approvals are complete.
* No dependent artifact is invalidated.
* No unresolved mandatory issue remains.

---

# 29. Non-Goals

The first version of the system should not assume that it must:

* Automatically deploy code to production.
* Automatically change ERP production data.
* Automatically approve business mappings.
* Invent missing schema information.
* Replace the human integration architect.
* Support every ERP and every integration type simultaneously.
* Solve every document format beyond the defined templates.
* Guarantee database execution solely through code-generation validation.

The initial goal is controlled engineering automation, not unrestricted autonomous production deployment.

---

# 30. Initial Product Boundary

The first implementation should focus on a single end-to-end happy path:

```text
One requirement
+
One approved schema/context
+
One FDD template
+
One TDD template
        ↓
Context Analysis
        ↓
FDD Generation
        ↓
Human Approval
        ↓
TDD Generation
        ↓
Human Approval
        ↓
SQL Generation
        ↓
Human Approval
        ↓
PL/SQL PKS/PKB Generation
        ↓
Validation
        ↓
Human Approval
        ↓
Versioned Output
```

The first version should establish the architecture and governance model correctly before expanding the number of supported integration scenarios.

---

# 31. Expected User Experience

A user should be able to create a project and provide:

```text
Business Requirement
Schema / ERP Context
FDD Google Docs Template
TDD Google Docs Template
```

The system should then present the current stage and generated artifact.

For example:

```text
PROJECT: Customer Extraction

Current Stage:
FDD REVIEW

Context Analysis: APPROVED
FDD: PENDING HUMAN REVIEW
TDD: LOCKED
SQL: LOCKED
PL/SQL: LOCKED

Automated Checks:
Schema Validation       ✓
Mapping Validation      ✓
Required Sections       ✓
Assumption Detection   ✓

[View FDD]
[Approve]
[Request Changes]
[Reject]
```

Once the user approves the FDD:

```text
FDD: APPROVED
TDD: GENERATING
```

The next stage then becomes available.

This provides an explicit, understandable workflow rather than hiding agent activity behind a single autonomous execution.

---

# 32. Success Criteria

The system should ultimately demonstrate that it can:

1. Accept a real ERP integration requirement.
2. Consume supplied schema/context.
3. Correctly identify supported entities and relationships.
4. Produce an FDD using the supplied Google Docs template.
5. Preserve template formatting.
6. Stop for human review.
7. Produce a TDD after FDD approval.
8. Stop for human review again.
9. Generate SQL from the approved design.
10. Generate complete `.pks` and `.pkb` files.
11. Validate generated code and cross-artifact consistency.
12. Maintain artifact versions.
13. Track human decisions and comments.
14. Invalidate dependent artifacts when upstream design changes.
15. Prevent unapproved artifacts from becoming deployment-ready.

---

# 33. Guiding Principle

The fundamental design principle of the system is:

> **AI accelerates engineering work; humans retain engineering authority.**

The platform should optimize for:

```text
Accuracy
+
Traceability
+
Reviewability
+
Consistency
+
Repeatability
+
Human Control
```

rather than maximum autonomy.

---

# 34. Instruction to the Engineering Agent

This problem statement is the high-level source of truth for implementation.

Before writing substantial production code, the engineering agent must:

1. Decompose the problem into logical implementation phases.
2. Identify functional, architectural, integration, security, data, document-generation, code-generation, and workflow risks.
3. Identify ambiguities and missing requirements.
4. Propose an implementation architecture.
5. Define clear interfaces between components.
6. Define the artifact and approval state model.
7. Define the dependency/versioning model.
8. Define an incremental development plan.
9. Implement and validate the system phase by phase.
10. Keep each phase independently testable.

The engineering agent must not assume that the largest possible architecture should be implemented immediately.

The implementation should start with a small end-to-end vertical slice and progressively add capabilities.

At every implementation stage, the engineering agent should maintain the separation between:

```text
AI reasoning
AI generation
Automated validation
Human approval
Artifact persistence
Artifact execution/deployment
```

These responsibilities must remain explicit throughout the system architecture.
