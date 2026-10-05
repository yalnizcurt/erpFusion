/** Reject new warnings/errors while retaining the explicitly recorded legacy debt. */
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

interface Diagnostic {
  file: string;
  code: string;
  message: string;
  source_hash: string;
}
interface RawDiagnostic {
  filename: string;
  code: string;
  message: string;
  labels: { span: { line: number } }[];
}
interface Ledger {
  owner: string;
  captured_on: string;
  policy: string;
  diagnostics: Diagnostic[];
}

const execution = spawnSync(process.execPath, ['./node_modules/oxlint/bin/oxlint', '--format=json'], {
  encoding: 'utf8',
});
if (execution.error || execution.status === null || execution.status > 1) {
  throw execution.error ?? new Error(execution.stderr || 'Oxlint did not complete');
}
const report = JSON.parse(execution.stdout) as { diagnostics: RawDiagnostic[] };
if (!Array.isArray(report.diagnostics)) throw new Error('Unexpected Oxlint diagnostic format');
const ledgerPath = resolve('lint-baseline.json');
const ledger = JSON.parse(readFileSync(ledgerPath, 'utf8')) as Ledger;
const actual: Diagnostic[] = report.diagnostics.map((item) => {
  const line = item.labels[0]?.span.line;
  if (line === undefined) throw new Error('Lint diagnostic has no source position');
  const source = readFileSync(resolve(item.filename), 'utf8').split(/\r?\n/)[line - 1] ?? '';
  return {
    file: item.filename, code: item.code, message: item.message,
    source_hash: createHash('sha256').update(source).digest('hex'),
  };
});
const fingerprint = (value: Diagnostic): string => JSON.stringify(value);
const counts = (values: Diagnostic[]): Map<string, number> => {
  const result = new Map<string, number>();
  for (const item of values) {
    const key = fingerprint(item);
    result.set(key, (result.get(key) ?? 0) + 1);
  }
  return result;
};
const allowed = counts(ledger.diagnostics);
const introduced: Diagnostic[] = [];
for (const item of actual) {
  const key = fingerprint(item);
  const available = allowed.get(key) ?? 0;
  if (available > 0) allowed.set(key, available - 1);
  else introduced.push(item);
}
if (introduced.length) {
  for (const item of introduced) console.error(`NEW ${item.file} [${item.code}] ${item.message}`);
  process.exitCode = 1;
} else {
  const resolved = ledger.diagnostics.length - actual.length;
  console.log(`Lint ratchet passed: ${actual.length} legacy warnings remain; ${resolved} resolved entries.`);
  if (process.argv.includes('--prune-baseline')) {
    ledger.diagnostics = actual;
    writeFileSync(ledgerPath, JSON.stringify(ledger, null, 2) + '\n');
  }
}
