import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { seed, createProject, SAMPLE_BRIEF, generate, approve, revise, recordTests, publishRelease, isUnlocked, packageEligible, zipFiles } from './model.mjs';

const data = seed();
const project = createProject({ name: 'Fresh integration', client: 'Sample client', profile: data.profiles[0] });
project.brief = SAMPLE_BRIEF;
assert.throws(() => generate(project, 1), /preceding stage/);
for (let stage = 0; stage < 4; stage++) { generate(project, stage); approve(project, stage); }
assert.equal(packageEligible(project), true);
recordTests(project, ['Install', 'Output', 'Recovery'].map(name => ({ name, result: 'fail' })));
assert.throws(() => approve(project, 4), /must pass/);
recordTests(project, ['Install', 'Output', 'Recovery'].map(name => ({ name, result: 'pass' })));
approve(project, 4); publishRelease(project);
const snapshot = JSON.stringify(project.releases[0]);
revise(project, 0, 'Change the schedule');
assert.equal(isUnlocked(project, 1), false);
assert.equal(packageEligible(project), false);
assert.equal(project.stages[1].current, null);
assert.equal(project.stages[1].history[0].status, 'approved');
assert.equal(JSON.stringify(project.releases[0]), snapshot);
generate(project, 0); approve(project, 0);
assert.equal(project.stages[0].current.version, 2);
assert.equal(project.stages[1].current, null);
data.profiles[0].version++;
assert.equal(project.profile.version, 4);
const custom = { ...data.profiles[4], id: 'never-hardcoded', name: 'Fresh test ERP', prompt: 'Unique profile guidance', templates: [{ name: '{{package}}.custom', content: 'MOCK {{erp}} / {{project}} / {{revision}}' }] };
const fresh = createProject({ name: 'Custom onboarding', client: 'Sample client', profile: custom }); fresh.brief = SAMPLE_BRIEF;
for (let stage = 0; stage < 4; stage++) { generate(fresh, stage); approve(fresh, stage); }
assert.equal(fresh.stages[3].current.files[0].name, 'hr_invoice_extract.custom');
assert.match(fresh.stages[3].current.files[0].content, /Fresh test ERP/);
assert.equal(fresh.stages[2].current.sources.prompt, 'Unique profile guidance');
const zip = zipFiles(project.releases[0].files);
assert.equal(new DataView(zip.buffer).getUint32(0, true), 0x04034b50);
await writeFile('/private/tmp/erpfusion-mock-check.zip', zip);
console.log('Mock checks passed: stage ordering, failed-test gate, revisions/history, pinned profiles, fresh ERP configuration and ZIP output.');
