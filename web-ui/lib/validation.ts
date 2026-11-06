import { readFile, realpath } from "node:fs/promises";
import path from "node:path";

export type ValidationRun = {
  run_id: string;
  execution_id: string;
  status: string;
  action_count: number;
  event_count: number;
  step_count: number;
  lease_epoch: number;
  url: string;
  heading: string;
};

export type ValidationReport = {
  started_at: string;
  finished_at: string;
  status: string;
  runs: ValidationRun[];
  checks_passed: number;
  checks_total: number;
  llm_calls: number | null;
  bench_stopped: boolean;
};

const images = new Set([
  "run-1-query-entered.png", "run-1-result.png",
  "run-2-query-entered.png", "run-2-result.png"
]);

async function readEvidence(name: string, directory: string): Promise<Buffer> {
  const root = await realpath(directory);
  const file = await realpath(path.join(root, name));
  if (path.dirname(file) !== root) throw new Error("Evidence outside archive");
  return readFile(file);
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value.length) throw new Error("Invalid text");
  return value;
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error("Invalid count");
  }
  return value;
}

export async function readValidation(
  directory = process.env.EMULYTIX_VALIDATION_DIR
): Promise<ValidationReport | null> {
  if (!directory) return null;
  try {
    const source = JSON.parse((await readEvidence("validation.json", directory)).toString("utf8"));
    if (!Array.isArray(source.runs) || !source.runs.length || !Array.isArray(source.checks)) return null;
    const started_at = text(source.started_at);
    const finished_at = text(source.finished_at);
    if (!Number.isFinite(Date.parse(started_at)) || !Number.isFinite(Date.parse(finished_at))) return null;
    const runs = source.runs.map((run: Record<string, unknown>): ValidationRun => {
      const url = text(run.url);
      if (url !== "https://fr.wikipedia.org/wiki/Football") throw new Error("Unexpected result URL");
      return {
        run_id: text(run.run_id), execution_id: text(run.execution_id), status: text(run.status),
        action_count: count(run.action_count), event_count: count(run.event_count),
        step_count: count(run.step_count), lease_epoch: count(run.lease_epoch),
        url, heading: text(run.heading)
      };
    });
    if (!source.checks.every((check: { passed: unknown }) => typeof check.passed === "boolean")) return null;
    return {
      started_at, finished_at, status: text(source.status), runs,
      checks_passed: source.checks.filter((check: { passed: boolean }) => check.passed).length,
      checks_total: source.checks.length,
      llm_calls: source.inference?.llm_calls == null ? null : count(source.inference.llm_calls),
      bench_stopped: source.bench_cleanup?.stopped_after_validation === true
    };
  } catch {
    return null;
  }
}

export async function readValidationImage(
  name: string, directory = process.env.EMULYTIX_VALIDATION_DIR
): Promise<Buffer | null> {
  if (!directory || !images.has(name)) return null;
  try {
    const bytes = await readEvidence(name, directory);
    return bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) ? bytes : null;
  } catch {
    return null;
  }
}
