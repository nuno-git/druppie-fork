// Verify that `docker compose up` actually runs inside the sandbox.
import { launchSandbox, defaultSandboxLaunchOptions } from "../dist/sandbox/lifecycle.js";

const run = async (s, cmd) => {
  const chunks = [];
  const exit = await s.client.execStream(
    { command: cmd, timeout: 120 },
    (buf) => chunks.push(buf.toString()),
  );
  return { out: chunks.join(""), exit };
};

const s = await launchSandbox({ ...defaultSandboxLaunchOptions() });
console.log(`[smoketest] sandbox ${s.containerName} @ :${s.hostPort}`);
try {
  await s.client.post("/write", {
    path: "compose.yml",
    content: `services:
  hello:
    image: hello-world
`,
  });

  console.log("\n$ docker compose up --exit-code-from hello");
  const up = await run(s, "cd /workspace && docker compose up --exit-code-from hello hello 2>&1");
  console.log(up.out.replace(/^/gm, "    "));
  console.log(`  exit: ${JSON.stringify(up.exit)}`);

  console.log("\n$ docker compose down");
  const down = await run(s, "cd /workspace && docker compose down 2>&1");
  console.log(down.out.replace(/^/gm, "    "));
} finally {
  s.stop();
  console.log("\n[smoketest] stopped");
}
