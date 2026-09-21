#!/usr/bin/env node
/** Запускает Playwright MCP и передаёт ему секреты без участия модели. */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "..");
const secretsPath = path.join(projectRoot, ".env.local");

// Простой разбор dotenv достаточен для токена и списка origin.
if (fs.existsSync(secretsPath)) {
  const lines = fs.readFileSync(secretsPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const separator = trimmed.indexOf("=");
    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

const npx = process.platform === "win32" ? "npx.cmd" : "npx";
const args = [
  "-y",
  "@playwright/mcp@latest",
  "--user-data-dir=.api-cartographer/browser-profile",
  "--output-dir=output/browser",
  "--save-session",
  "--init-page=.opencode/playwright/init-page.ts",
];
if (fs.existsSync(secretsPath)) args.push(`--secrets=${secretsPath}`);

const origins = process.env.API_BEARER_ORIGINS;
if (origins) args.push(`--allowed-origins=${origins.split(",").join(";")}`);

const child = spawn(npx, args, {
  cwd: projectRoot,
  env: process.env,
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});

