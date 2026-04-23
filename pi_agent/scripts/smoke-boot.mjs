/**
 * Smoke test: launch a sandbox, ping its daemon, tear down.
 *
 * Validates level-2 of the e2e for execute_coding_task_pi — that the
 * vendored sandbox image + sysbox-runc actually boot and expose a
 * working daemon on loopback. No LLM calls.
 */
import { defaultSandboxLaunchOptions, launchSandbox } from "../dist/sandbox/lifecycle.js";

process.env.ONESHOT_SANDBOX_RUNTIME = process.env.ONESHOT_SANDBOX_RUNTIME ?? "sysbox-runc";

const opts = {
  ...defaultSandboxLaunchOptions(),
  timeoutSec: 120,
};

console.log(`[smoke] launching sandbox (runtime=${opts.runtime}, image=${opts.image})`);
const sb = await launchSandbox(opts);
console.log(`[smoke] container=${sb.containerName} host-port=${sb.hostPort}`);

try {
  const res = await fetch(`http://127.0.0.1:${sb.hostPort}/health`, {
    headers: { Authorization: `Bearer ${sb.authToken}` },
  });
  console.log(`[smoke] /health -> ${res.status} ${await res.text()}`);

  const exec = await fetch(`http://127.0.0.1:${sb.hostPort}/exec`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${sb.authToken}`,
      "content-type": "application/json",
    },
    // Daemon shape: {command: "<bash>", cwd?, timeout?}.
    body: JSON.stringify({ command: "echo hello-from-sandbox && uname -a && id", timeout: 10 }),
  });
  console.log(`[smoke] /exec -> ${exec.status}`);
  const text = await exec.text();
  console.log(text.slice(0, 400));
} finally {
  sb.stop();
  console.log(`[smoke] stopped`);
}
