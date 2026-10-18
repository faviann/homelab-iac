import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { delimiter, dirname, join } from 'node:path';

// npx puts the package's bin directory on PATH, but node cannot resolve the
// package from this file's location.
const renovateBin = process.env.PATH.split(delimiter)
  .map((dir) => join(dir, 'renovate'))
  .find(existsSync);
const dist = dirname(realpathSync(renovateBin));
const { getConfig } = await import(join(dist, 'config/defaults.js'));
const { mergeChildConfig } = await import(join(dist, 'config/utils.js'));
const { resolveConfigPresets } = await import(join(dist, 'config/presets/index.js'));
const { applyPackageRules } = await import(join(dist, 'util/package-rules/index.js'));

const repoConfig = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const { config } = await resolveConfigPresets(repoConfig);
const base = mergeChildConfig(getConfig(), config);

const outcomes = [];
for (const update of JSON.parse(readFileSync(0, 'utf8'))) {
  const dep = { datasource: 'docker', packageName: update.depName, ...update };
  const result = await applyPackageRules(mergeChildConfig(base, dep), 'update');
  outcomes.push({
    automerge: result.automerge,
    dependencyDashboardApproval: result.dependencyDashboardApproval,
    schedule: result.schedule,
  });
}
console.log(JSON.stringify(outcomes));
