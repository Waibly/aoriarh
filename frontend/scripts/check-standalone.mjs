// Test technique du serveur livré, sans backend ni appel LLM.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { cp, mkdtemp, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const root = fileURLToPath(new URL("../", import.meta.url));
const runtime = await mkdtemp(join(tmpdir(), "aoriarh-standalone-"));
let child;
let logs = "";
try {
  await cp(join(root, ".next/standalone"), runtime, {
    recursive: true,
    // Le build local peut tracer un .env : aucun secret nécessaire au test.
    filter: (source) => !/^\.env(?:\.|$)/.test(basename(source)),
  });
  await cp(join(root, ".next/static"), join(runtime, ".next/static"), { recursive: true });
  await cp(join(root, "public"), join(runtime, "public"), { recursive: true });
  const requireRuntime = createRequire(join(runtime, "server.js"));
  function checkNoDevDependencies() {
    for (const name of ["typescript", "jest", "eslint", "shadcn"]) {
      assert.throws(() => requireRuntime.resolve(name), { code: "MODULE_NOT_FOUND" }, `${name} présent dans le serveur livré`);
    }
  }
  checkNoDevDependencies();
  const socket = createServer();
  socket.listen(0, "127.0.0.1");
  await once(socket, "listening");
  const port = socket.address().port;
  await new Promise((resolve, reject) => socket.close((error) => error ? reject(error) : resolve()));
  child = spawn(process.execPath, ["server.js"], {
    cwd: runtime,
    env: {
      NODE_ENV: "production", NEXT_TELEMETRY_DISABLED: "1",
      HOSTNAME: "127.0.0.1", PORT: String(port),
      AUTH_SECRET: "standalone-smoke-test-only-not-a-real-secret",
      AUTH_TRUST_HOST: "true", PATH: "",
      npm_config_offline: "true", npm_config_registry: "http://127.0.0.1:9",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (data) => { logs += data; });
  child.stderr.on("data", (data) => { logs += data; });
  let spawnError;
  child.on("error", (error) => { spawnError = error; });
  const base = `http://127.0.0.1:${port}`;
  let ready = false;
  // Attente de démarrage bornée, jamais de relance du serveur.
  for (const deadline = Date.now() + 30_000; Date.now() < deadline;) {
    if (spawnError) throw spawnError;
    assert.equal(child.exitCode, null, `Le serveur a quitté : ${logs}`);
    try {
      await fetch(`${base}/favicon.svg`, { signal: AbortSignal.timeout(1000) });
      ready = true;
      break;
    } catch { await delay(200); }
  }
  assert.ok(ready, `Démarrage expiré : ${logs}`);
  for (const path of ["/login", "/demo", "/favicon.svg", "/api/auth/session"]) {
    const response = await fetch(`${base}${path}`, { signal: AbortSignal.timeout(10_000) });
    assert.equal(response.status, 200, `${path} : ${logs}`);
    assert.equal(response.headers.get("x-content-type-options"), "nosniff");
    assert.equal(response.headers.get("x-frame-options"), "DENY");
    assert.ok(response.headers.get("content-security-policy"));
    if (path === "/api/auth/session") assert.equal(await response.json(), null);
    if (path === "/login") {
      const html = await response.text();
      const asset = html.match(/(?:src|href)="([^" ]*\/_next\/static\/[^" ]+)"/);
      assert.ok(asset, "Asset Next.js absent de la page de connexion");
      const staticResponse = await fetch(new URL(asset[1], base), { signal: AbortSignal.timeout(10_000) });
      assert.equal(staticResponse.status, 200, "Asset Next.js inaccessible");
    }
  }
  checkNoDevDependencies();
  assert.doesNotMatch(logs, /Installing dependencies|npm (?:install|warn|error)/i);
  console.log("Standalone OK : pages, session anonyme, assets et en-têtes ; aucune dépendance de développement.");
} finally {
  if (child && child.exitCode === null && child.pid) {
    const exited = once(child, "exit");
    child.kill("SIGTERM");
    const timeout = setTimeout(() => child.kill("SIGKILL"), 5000);
    try { await exited; } finally { clearTimeout(timeout); }
  }
  // Uniquement le répertoire temporaire créé par ce test.
  await rm(runtime, { recursive: true, force: true });
}
