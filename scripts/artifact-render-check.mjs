// Render one artifact in headless Chromium and report what broke.
// docs/artifact-server.md has the invocation and the workstation browser setup.
import {existsSync, readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {parseArgs} from "node:util";

const DEFAULT_SERVER = "https://artifact-server.public.faviann.com";
const ARTIFACT_ID = /^art_[0-9a-f-]{36}$/u;

function usage(message) {
  console.error(`artifact-render-check: ${message}`);
  console.error("usage: <artifact-id | url> [--token-file <path>] [--server <origin>] [--out <png>]");
  process.exit(2);
}

function findOnPath(candidate) {
  for (const directory of (process.env.PATH ?? "").split(path.delimiter)) {
    const file = candidate(directory);
    if (file !== null && existsSync(file)) return file;
  }
  return null;
}

// The script runs outside any package, so `import "playwright"` cannot resolve.
// npx puts the package's .bin on PATH; load the package beside it.
async function loadPlaywright() {
  const entry = findOnPath((directory) =>
    path.basename(directory) === ".bin" ? path.join(directory, "..", "playwright", "index.mjs") : null
  );
  if (entry === null) usage("playwright not found; run through `npx -y -p playwright@1.64.1 node ...`");
  return import(pathToFileURL(entry).href);
}

function resolveTarget(target, server, token) {
  if (ARTIFACT_ID.test(target)) {
    if (token === null) usage("an artifact id needs --token-file");
    return {kind: "session", server, artifactId: target};
  }
  try {
    return {kind: "url", url: new URL(target).href};
  } catch {
    usage(`not an artifact id or URL: ${target}`);
  }
}

async function bootstrapUrl({server, artifactId}, token) {
  const response = await fetch(
    `${server}/api/v1/artifacts/${encodeURIComponent(artifactId)}/content-sessions`,
    {method: "POST", headers: {authorization: `Bearer ${token}`}},
  );
  if (response.status !== 201) {
    throw new Error(`content session for ${artifactId}: HTTP ${response.status} ${await response.text()}`);
  }
  return (await response.json()).bootstrapUrl;
}

const {values, positionals} = parseArgs({
  allowPositionals: true,
  options: {
    "token-file": {type: "string"},
    server: {type: "string", default: DEFAULT_SERVER},
    out: {type: "string"},
  },
});
if (positionals.length !== 1) usage("expected exactly one artifact id or URL");

const token = values["token-file"] === undefined
  ? null
  : readFileSync(values["token-file"], "utf8").trim();
const target = resolveTarget(positionals[0], values.server.replace(/\/+$/u, ""), token);
const screenshot = path.resolve(
  values.out ?? path.join(tmpdir(), `artifact-render-${process.pid}.png`),
);
const {chromium} = await loadPlaywright();
// Playwright's downloaded browser lacks its system libraries on the workstation.
const browser = await chromium.launch({
  executablePath: findOnPath((directory) => path.join(directory, "chromium")) ?? undefined,
});
const report = {url: null, status: null, consoleErrors: [], pageErrors: [], failedRequests: [], screenshot};
try {
  const context = await browser.newContext();
  let startUrl = target.url;
  if (target.kind === "session") {
    // The exchange sets the content-session cookie in the context's jar, so the
    // page then loads the artifact itself instead of the bootstrap redirect page.
    const bootstrap = new URL(await bootstrapUrl(target, token));
    const exchange = await context.request.get(bootstrap.href);
    if (!exchange.ok()) throw new Error(`content session exchange: HTTP ${exchange.status()}`);
    bootstrap.searchParams.delete("__artifact_bootstrap");
    startUrl = bootstrap.href;
  }
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") report.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => report.pageErrors.push(String(error)));
  page.on("requestfailed", (request) => {
    report.failedRequests.push({url: request.url(), error: request.failure()?.errorText ?? "failed"});
  });
  page.on("response", (response) => {
    if (response.status() >= 400) report.failedRequests.push({url: response.url(), status: response.status()});
  });
  const response = await page.goto(startUrl, {waitUntil: "load", timeout: 60_000});
  // A page that polls never goes idle; report what it did in the first seconds.
  await page.waitForLoadState("networkidle", {timeout: 5_000}).catch(() => {});
  report.status = response?.status() ?? null;
  report.url = page.url();
  await page.screenshot({path: screenshot, fullPage: true});
} finally {
  await browser.close();
}

console.log(JSON.stringify(report, null, 2));
const ok = report.status !== null && report.status >= 200 && report.status < 300 &&
  report.consoleErrors.length === 0 && report.pageErrors.length === 0;
process.exit(ok ? 0 : 1);
