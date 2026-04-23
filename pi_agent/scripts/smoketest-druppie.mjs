// Spin up a sandbox, mint a GitHub App installation token, clone druppie-fork
// into the sandbox via bundle, verify the files are there, tear down.
import { launchSandbox, defaultSandboxLaunchOptions } from "../dist/sandbox/lifecycle.js";
import { loadAppCredentialsFromEnv, mintInstallationToken } from "../dist/github/app.js";
import { cloneSourceIntoSandbox } from "../dist/sandbox/source-clone.js";

const creds = loadAppCredentialsFromEnv();
if (!creds) {
  console.error("load GITHUB_APP_* env vars first (source druppie-fork/.env)");
  process.exit(1);
}

console.log("▸ minting App installation token…");
const minted = await mintInstallationToken(creds);
console.log(`  ok — expires ${minted.expiresAt}`);

console.log("\n▸ launching sandbox…");
const s = await launchSandbox({ ...defaultSandboxLaunchOptions() });
console.log(`  ${s.containerName} @ :${s.hostPort}`);

try {
  const remoteUrl = process.env.ONESHOT_TEST_REPO ?? "https://github.com/nuno-git/druppie-fork";
  const branch = process.env.ONESHOT_TEST_BRANCH ?? "main";

  console.log(`\n▸ cloning ${remoteUrl}@${branch} into sandbox…`);
  await cloneSourceIntoSandbox(
    s.client,
    { host: "127.0.0.1", port: s.hostPort, authToken: s.authToken },
    { remoteUrl, branch, token: minted.token },
  );
  console.log("  imported");

  console.log("\n▸ sanity checks inside sandbox:");
  const chunks = [];
  await s.client.execStream(
    { command: "cd /workspace && pwd && git branch --show-current && git log --oneline -3 && ls | head -20 && wc -l README.md 2>/dev/null || true" },
    (buf) => chunks.push(buf.toString()),
  );
  console.log(chunks.join("").replace(/^/gm, "    "));
} finally {
  s.stop();
  console.log("\n▸ stopped");
}
