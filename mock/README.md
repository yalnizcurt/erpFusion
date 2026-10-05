# HighStudio JavaScript mock

A standalone, dependency-free product prototype. It does not change the production frontend or backend.

Start it from the repository root:

```sh
node mock/server.mjs
```

Open **http://localhost:4174**. Set `PORT` to use another port. The server only listens on the local loopback interface.

## Try the flow

1. Home → Create New → choose client, ERP, type and due date.
2. Studio → upload a sample TXT/Markdown file or choose Use sample brief.
3. Analyze and approve Requirements, then generate/review/approve FDD, TDD and Package in order.
4. Package files → inspect and download configured individual files after package approval.
5. Sandbox → record simulated results → give explicit tester sign-off.
6. Release → publish → download the sample ZIP, which includes configured files and a manifest with SHA-256 checksums.
7. Revise an earlier stage: downstream gates lock, old decisions remain in History, and previous releases stay downloadable.
8. ERP profiles → Add ERP → configure its sample template → use it in a new project. Profile updates do not change already pinned projects.

Home includes project search, ERP/type/status filters, pagination, dates and eligible package downloads. Studio links survive refresh; demo work is saved locally. Header, sidebar and footer stay fixed, with scrolling contained inside the workspace.

## Boundaries

**Use sample data only.** Project text and mock configuration are saved in this browser's local storage. Uploaded file bytes are not retained; PDF/DOCX uploads list metadata only. TXT/Markdown text is read locally, capped at 20,000 characters. About → Reset demo clears saved demo data.

AI generation, validation, review roles and sandbox testing are simulated. There is no authentication, ERP connection, installation or production deployment. Generated code is marked as a non-deployable stub. All assets are local; no analytics, telemetry, external fonts or API requests.

Run the small behavior check:

```sh
node mock/check.mjs
unzip -t /private/tmp/erpfusion-mock-check.zip
```
