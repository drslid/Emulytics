export const dashboardOutcomes = [
  { key: "succeeded", label: "Réussies", color: "success" },
  { key: "failed", label: "Échouées", color: "failure" },
  { key: "cancelled", label: "Annulées", color: "cancelled" },
  { key: "needs_review", label: "À vérifier", color: "review" },
] as const;

export type DashboardCounts = { succeeded: number; failed: number; cancelled: number; needs_review: number };
export type DashboardDay = DashboardCounts & { date: string };
export type DashboardSnapshot = {
  observed_at: string;
  timezone: string;
  window_start: string;
  window_end: string;
  days: DashboardDay[];
  totals: DashboardCounts & { finished: number };
};
export type DashboardCapacity = {
  observed_at: string;
  workers: { total: number; busy: number; idle: number } | null;
  devices: { total: number; connected: number; ready: number } | null;
  unconfirmedDevices: number | null;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function count(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function instant(value: unknown): value is string { return typeof value === "string" && Number.isFinite(Date.parse(value)); }

export function dayTotal(day: DashboardCounts): number {
  return dashboardOutcomes.reduce((sum, outcome) => sum + day[outcome.key], 0);
}

export function summarizeDays(days: DashboardDay[]): DashboardSnapshot["totals"] {
  const totals = { succeeded: 0, failed: 0, cancelled: 0, needs_review: 0, finished: 0 };
  for (const day of days) for (const outcome of dashboardOutcomes) totals[outcome.key] += day[outcome.key];
  totals.finished = dayTotal(totals);
  return totals;
}

export function percentOf(value: number | null, total: number | null): number | null {
  if (!count(value) || !count(total) || total === 0 || value > total) return null;
  return value / total * 100;
}

export function parseDashboardSnapshot(value: unknown): DashboardSnapshot {
  const input = record(value), totals = record(input.totals);
  if (!instant(input.observed_at) || !instant(input.window_start) || !instant(input.window_end) ||
      Date.parse(input.window_start) > Date.parse(input.window_end) || typeof input.timezone !== "string" ||
      !Array.isArray(input.days) || input.days.length !== 7) throw new Error("Invalid dashboard snapshot");
  new Intl.DateTimeFormat("en", { timeZone: input.timezone });
  let previous = -Infinity;
  for (const item of input.days) {
    const day = record(item);
    if (typeof day.date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(day.date)) throw new Error("Invalid dashboard day");
    const date = Date.parse(day.date + "T00:00:00Z");
    if (!Number.isFinite(date) || new Date(date).toISOString().slice(0, 10) !== day.date ||
        (previous !== -Infinity && date - previous !== 86_400_000) ||
        dashboardOutcomes.some(outcome => !count(day[outcome.key]))) throw new Error("Invalid dashboard day");
    previous = date;
  }
  const expected = summarizeDays(input.days as DashboardDay[]);
  if (Object.entries(expected).some(([key, total]) => !count(totals[key]) || totals[key] !== total)) throw new Error("Inconsistent dashboard totals");
  return input as DashboardSnapshot;
}

export function parseDashboardCapacity(value: unknown): DashboardCapacity {
  const input = record(value), capacity = record(input.capacity), fleet = record(input.fleet);
  if (!instant(input.observed_at)) throw new Error("Invalid capacity snapshot");
  const workers = count(capacity.live_workers) && count(capacity.busy_workers) && count(capacity.idle_workers) &&
    capacity.busy_workers + capacity.idle_workers === capacity.live_workers
    ? { total: capacity.live_workers, busy: capacity.busy_workers, idle: capacity.idle_workers } : null;
  const devices = count(fleet.total) && count(fleet.connected) && count(fleet.ready) && fleet.ready <= fleet.connected && fleet.connected <= fleet.total
    ? { total: fleet.total, connected: fleet.connected, ready: fleet.ready } : null;
  const unconfirmedDevices = devices && count(fleet.unknown) && fleet.unknown + devices.connected <= devices.total ? fleet.unknown : null;
  return { observed_at: input.observed_at, workers, devices, unconfirmedDevices };
}
