#!/usr/bin/env node
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { platform } from "node:os";

const args = process.argv.slice(2);
const has = (flag) => args.includes(flag);
const value = (flag, fallback) => {
  const i = args.indexOf(flag);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const repo = value("--repo", "https://github.com/vmeducatedlucifer-commits/Bhati-Ai-Agent.git");
const target = resolve(value("--dir", "rawal-ai"));
const mode = value("--mode", "docker");
const token = process.env.RAWAL_GITHUB_TOKEN || process.env.GH_TOKEN || process.env.GITHUB_TOKEN || "";

function run(command, commandArgs, cwd = process.cwd()) {
  const displayArgs = commandArgs.map((arg) =>
    arg.includes("Authorization: Bearer ") ? "http.extraheader=Authorization: Bearer [REDACTED]" : arg,
  );
  console.log(`\n$ ${command} ${displayArgs.join(" ")}`);
  const env = { ...process.env };
  execFileSync(command, commandArgs, { cwd, stdio: "inherit", env });
}

function git(commandArgs, cwd = process.cwd()) {
  const args = token
    ? ["-c", `http.extraheader=${`Authorization: Bearer ${token}`}`, ...commandArgs]
    : commandArgs;
  run("git", args, cwd);
}

if (has("--help") || has("-h")) {
  console.log(`Rawal AI installer\n\nUsage: npx rawal [options]\n  --dir <folder>     Installation folder (default: rawal-ai)\n  --mode docker      Build and start with Docker Compose (default)\n  --mode local       Install local dependencies and print dev commands\n  --repo <url>       Repository URL override\n  --help             Show this help`);
  process.exit(0);
}

if (!token && repo.includes("github.com/vmeducatedlucifer-commits/")) {
  console.error("Private Rawal AI repository access requires RAWAL_GITHUB_TOKEN, GH_TOKEN, or GITHUB_TOKEN.");
  console.error("Create a read-only token and provide it via the environment; never paste it into this command or commit it.");
  process.exit(1);
}

if (existsSync(join(target, ".git"))) {
  git(["pull", "--ff-only"], target);
} else {
  mkdirSync(resolve(target, ".."), { recursive: true });
  git(["clone", repo, target]);
}

if (mode === "local") {
  if (platform() === "win32") run("powershell", ["-ExecutionPolicy", "Bypass", "-File", "install.ps1"], target);
  else run("bash", ["install.sh"], target);
  console.log("\nRawal AI installed. Configure backend/.env, then run `make dev`.");
} else if (mode === "docker") {
  run("docker", ["compose", "up", "--build", "-d"], target);
  console.log("\nRawal AI is running at http://localhost:8000");
} else {
  console.error(`Unknown mode: ${mode}. Use --mode docker or --mode local.`);
  process.exit(2);
}
