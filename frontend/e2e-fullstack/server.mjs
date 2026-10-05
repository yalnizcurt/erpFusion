// Test-only supervisor. Never reads backend/.env or opens an existing database.
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const backend = fileURLToPath(new URL('../../backend/', import.meta.url));
const python = process.env.E2E_PYTHON || resolve(backend, '.venv/bin/python');
const directory = mkdtempSync(resolve(tmpdir(), 'erpfusion-fullstack-'));
mkdirSync(resolve(directory, 'private-artifacts'), { mode: 0o700 });
const env = {
  PATH: process.env.PATH, PYTHONPATH: backend, PYTHONUNBUFFERED: '1',
  APP_ENV: 'development', AUTH_MODE: 'development',
  DEV_IDENTITY_USER_ID: 'fullstack-acceptance-fixture', DEV_IDENTITY_ROLES: '["platform_admin"]',
  DATABASE_URL: `sqlite+aiosqlite:///${directory}/acceptance.db`,
  ARTIFACT_STORAGE_PATH: resolve(directory, 'private-artifacts'), ARTIFACT_STORAGE_BACKEND: 'local',
  DEMO_MODE: 'true', LLM_PROVIDER: 'mock', CORS_ORIGINS: '["http://127.0.0.1:4183"]',
  EXECUTION_SIMULATOR_ENABLED: 'true',
};
const children = [];
let stopping = false;
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  await Promise.all(children.map((child) => new Promise((done) => {
    if (child.exitCode !== null || child.signalCode !== null) { done(); return; }
    child.once('exit', done); child.kill('SIGTERM');
    const timer = setTimeout(() => child.kill('SIGKILL'), 5000); timer.unref();
  })));
  rmSync(directory, { recursive: true, force: true });
  process.exit(code);
}
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { void stop(); });
// Existing explicit initializer applies the actual migrations; no ERP seed is loaded.
const initialized = spawnSync(python, ['-m', 'app.cli', 'development-init'], { cwd: directory, env, stdio: 'inherit' });
if (initialized.status !== 0) { await stop(1); }
for (const args of [
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8183'],
  ['-m', 'app.cli.generation_worker'],
  ['-m', 'app.cli.execution_worker'],
]) {
  const child = spawn(python, args, { cwd: directory, env, stdio: 'inherit' });
  children.push(child);
  child.on('error', () => { void stop(1); });
  child.on('exit', (code) => { if (!stopping) void stop(code || 1); });
}
