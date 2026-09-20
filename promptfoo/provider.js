const { spawnSync } = require("node:child_process");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..");

function run(prompt) {
  let request;
  try {
    request = JSON.parse(prompt);
  } catch (error) {
    process.stderr.write(`Promptfoo provider received invalid JSON: ${error.message}\n`);
    process.exit(1);
  }

  if (!request.session_id || !Array.isArray(request.messages)) {
    process.stderr.write("Prompt must contain session_id and messages[]\n");
    process.exit(1);
  }

  const input = request.messages
    .map((message) => JSON.stringify({ session_id: request.session_id, message }))
    .join("\n") + "\n";

  const result = spawnSync("bash", ["scripts/chat.sh", "--jsonl"], {
    cwd: repoRoot,
    input,
    encoding: "utf8",
    env: process.env,
  });

  if (result.error) {
    process.stderr.write(`${result.error.message}\n`);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.stderr.write(`chat.sh exited with ${result.status}: ${result.stderr || ""}\n`);
    process.exit(result.status || 1);
  }

  const outputLines = result.stdout.trim().split(/\r?\n/).filter(Boolean);
  if (outputLines.length !== request.messages.length) {
    process.stderr.write(
      `Expected ${request.messages.length} JSONL responses, got ${outputLines.length}: ${result.stdout}\n`,
    );
    process.exit(1);
  }

  let responses;
  try {
    responses = outputLines.map((line) => JSON.parse(line));
  } catch (error) {
    process.stderr.write(`Chat output was not valid JSONL: ${error.message}\n`);
    process.exit(1);
  }

  process.stdout.write(JSON.stringify(responses[responses.length - 1]));
}

run(process.argv[2] || "");
