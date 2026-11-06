import type { Execution } from "./console-types";

type Candidate = Pick<Execution, "id" | "status">;
export type ExecutionLiveSelection = { executionId: string | null; hidden: boolean };
const active = new Set(["leased", "running", "recovering", "verifying_state", "waiting_auth"]);

export function isExecutionLive(execution: Candidate): boolean { return active.has(execution.status); }

export function reconcileExecutionLive(executions: Candidate[], selection: ExecutionLiveSelection): ExecutionLiveSelection {
  const live = executions.filter(isExecutionLive);
  return { executionId: live.find(execution => execution.id === selection.executionId)?.id ?? live[0]?.id ?? null, hidden: selection.hidden };
}

export function toggleExecutionLive(executions: Candidate[], selection: ExecutionLiveSelection, executionId: string): ExecutionLiveSelection {
  const current = reconcileExecutionLive(executions, selection);
  if (!executions.some(execution => execution.id === executionId && isExecutionLive(execution))) return current;
  return { executionId, hidden: current.executionId === executionId && !current.hidden };
}
