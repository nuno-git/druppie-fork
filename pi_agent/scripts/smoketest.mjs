// End-to-end smoke test. Launch sandbox, exercise every endpoint, verify
// dockerd-in-sandbox is up, produce a git bundle, confirm bundle on host.
//
// Usage:
//   ONESHOT_SANDBOX_RUNTIME=sysbox-runc node scripts/smoketest.mjs
import { launchSandbox, defaultSandboxLaunchOptions } from "../dist/sandbox/lifecycle.js";

const ok = (name, v) => console.log(`  ✓ ${name}: ${v}`);
const section = (title) => console.log(`\n▸ ${title}`);

section("launch");
const s = await launchSandbox({ ...defaultSandboxLaunchOptions() });
ok("container", s.containerName);
ok("hostPort", s.hostPort);

try {
  section("health");
  ok("health", JSON.stringify(await s.client.get("/health")));

  section("exec — whoami / uname / which tools");
  const chunks = [];
  await s.client.execStream(
    { command: "whoami && uname -a && which docker node git python3 rg fd" },
    (buf) => chunks.push(buf.toString()),
  );
  console.log(chunks.join("").trimEnd().replace(/^/gm, "    "));

  section("dockerd inside the sandbox");
  const dchunks = [];
  const d = await s.client.execStream(
    { command: "docker version --format '{{.Server.Version}}' 2>&1 ; docker info --format '{{.ServerVersion}} ({{.Driver}})' 2>&1" },
    (buf) => dchunks.push(buf.toString()),
  );
  console.log(dchunks.join("").trimEnd().replace(/^/gm, "    "));
  ok("dockerd exit", JSON.stringify(d));

  section("file ops");
  ok("write", JSON.stringify(await s.client.post("/write", { path: "hello.txt", content: "hello from host\n" })));
  ok("read", JSON.stringify(await s.client.post("/read", { path: "hello.txt" })));
  ok("stat", JSON.stringify(await s.client.post("/stat", { path: "hello.txt" })));
  await s.client.post("/write", { path: "src/a.js", content: "console.log(1)\n" });
  await s.client.post("/write", { path: "src/b.js", content: "console.log(2)\n" });
  ok("find", JSON.stringify(await s.client.post("/find", { pattern: "**/*.js", path: "" })));
  ok("grep", JSON.stringify(await s.client.post("/grep", { pattern: "console", path: "src" })));

  section("git round-trip");
  ok("init", JSON.stringify(await s.client.post("/init", { branch: "main" })));
  const gchunks = [];
  const gexit = await s.client.execStream(
    { command: "git add -A && git commit -m 'seed' && git log --oneline" },
    (buf) => gchunks.push(buf.toString()),
  );
  console.log(gchunks.join("").trimEnd().replace(/^/gm, "    "));
  ok("git exit", JSON.stringify(gexit));
  const bundle = await s.client.post("/bundle", { refs: ["--all"], name: "run.bundle" });
  ok("bundle", JSON.stringify(bundle));

  section("bundle visible on host");
  const fs = await import("node:fs");
  const path = await import("node:path");
  const hostPath = path.join(s.bundleHostDir, "run.bundle");
  const stat = fs.statSync(hostPath);
  ok("hostPath", hostPath);
  ok("size", stat.size);
} finally {
  section("stop");
  s.stop();
  ok("stopped", s.containerName);
}
