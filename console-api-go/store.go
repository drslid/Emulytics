package main

import (
	"context"
	"encoding/json"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Summary struct {
	DevicesTotal    int64 `json:"devices_total"`
	WorkflowsTotal  int64 `json:"workflows_total"`
	RunsTotal       int64 `json:"runs_total"`
	RunsActive      int64 `json:"runs_active"`
	RunsNeedsReview int64 `json:"runs_needs_review"`
	RunsSucceeded   int64 `json:"runs_succeeded"`
}
type Device struct {
	DeviceID         string  `json:"device_id"`
	HostID           string  `json:"host_id"`
	Serial           string  `json:"serial"`
	Kind             string  `json:"kind"`
	Status           string  `json:"status"`
	DisplayName      string  `json:"display_name"`
	CreatedAt        string  `json:"created_at"`
	Availability     string  `json:"availability"`
	ActiveRunID      *string `json:"active_run_id"`
	LeaseExpiresAt   *string `json:"lease_expires_at"`
	ConnectionStatus string  `json:"connection_status"`
	WorkerLastSeenAt *string `json:"worker_last_seen_at"`
}
type FleetPage struct {
	Items       []Device `json:"items"`
	Total       int64    `json:"total"`
	Limit       int64    `json:"limit"`
	Offset      int64    `json:"offset"`
	WorkerHosts []string `json:"worker_hosts"`
}
type workerSignal struct {
	HostID  *string
	Status  string
	Metrics map[string]any
	Seen    time.Time
	Live    bool
}
type Counts struct {
	Succeeded   int64 `json:"succeeded"`
	Failed      int64 `json:"failed"`
	Cancelled   int64 `json:"cancelled"`
	NeedsReview int64 `json:"needs_review"`
}
type DashboardDay struct {
	Date string `json:"date"`
	Counts
}
type DashboardTotals struct {
	Counts
	Finished int64 `json:"finished"`
}
type Dashboard struct {
	ObservedAt  string          `json:"observed_at"`
	Timezone    string          `json:"timezone"`
	WindowStart string          `json:"window_start"`
	WindowEnd   string          `json:"window_end"`
	Days        []DashboardDay  `json:"days"`
	Totals      DashboardTotals `json:"totals"`
}
type postgresStore struct{ pool *pgxpool.Pool }

func stamp(value time.Time) string {
	if value.Nanosecond() == 0 {
		return value.UTC().Format("2006-01-02T15:04:05Z")
	}
	return value.UTC().Format("2006-01-02T15:04:05.000000Z")
}
func nullableStamp(value *time.Time) *string {
	if value == nil {
		return nil
	}
	result := stamp(*value)
	return &result
}

func (p *postgresStore) Ping(ctx context.Context) error { return p.pool.Ping(ctx) }
func (p *postgresStore) Summary(ctx context.Context) (Summary, error) {
	var value Summary
	err := p.pool.QueryRow(ctx, `SELECT (SELECT COUNT(*) FROM devices),(SELECT COUNT(*) FROM workflows WHERE workflow_id NOT LIKE 'emulator-system-%'),
COUNT(*),COUNT(*) FILTER(WHERE status IN ('queued','running')),
COUNT(*) FILTER(WHERE status='needs_review'),COUNT(*) FILTER(WHERE status='succeeded') FROM runs`).Scan(
		&value.DevicesTotal, &value.WorkflowsTotal, &value.RunsTotal, &value.RunsActive, &value.RunsNeedsReview, &value.RunsSucceeded)
	return value, err
}

func (p *postgresStore) Fleet(ctx context.Context, limit, offset int64) (FleetPage, error) {
	result := FleetPage{Items: []Device{}, WorkerHosts: []string{}, Limit: limit, Offset: offset}
	if err := p.pool.QueryRow(ctx, "SELECT count(*) FROM devices").Scan(&result.Total); err != nil {
		return result, err
	}
	rows, err := p.pool.Query(ctx, `SELECT d.device_id,d.host_id,d.serial,d.kind,d.status,d.display_name,d.created_at,
CASE WHEN l.quarantined OR (l.owner_id IS NOT NULL AND l.expires_at<=clock_timestamp()) THEN 'needs_review'
WHEN l.owner_id IS NOT NULL THEN 'busy' ELSE 'declared' END,e.run_id::text,l.expires_at
FROM devices d LEFT JOIN device_leases l ON l.device_id=d.device_id LEFT JOIN executions e ON e.id=l.execution_id
ORDER BY d.device_id LIMIT $1 OFFSET $2`, limit, offset)
	if err != nil {
		return result, err
	}
	for rows.Next() {
		var d Device
		var created time.Time
		var expires *time.Time
		if err = rows.Scan(&d.DeviceID, &d.HostID, &d.Serial, &d.Kind, &d.Status, &d.DisplayName, &created, &d.Availability, &d.ActiveRunID, &expires); err != nil {
			rows.Close()
			return result, err
		}
		d.CreatedAt = stamp(created)
		d.LeaseExpiresAt = nullableStamp(expires)
		result.Items = append(result.Items, d)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	rows, err = p.pool.Query(ctx, `SELECT host_id,status,metrics,last_seen_at,last_seen_at>clock_timestamp()-interval '20 seconds'
FROM service_heartbeats WHERE component='worker' ORDER BY last_seen_at DESC`)
	if err != nil {
		return result, err
	}
	workers := []workerSignal{}
	hosts := map[string]bool{}
	for rows.Next() {
		var w workerSignal
		var metrics []byte
		if err = rows.Scan(&w.HostID, &w.Status, &metrics, &w.Seen, &w.Live); err != nil {
			rows.Close()
			return result, err
		}
		_ = json.Unmarshal(metrics, &w.Metrics)
		workers = append(workers, w)
		if w.Live && w.Status == "ready" && w.HostID != nil && *w.HostID != "" {
			hosts[*w.HostID] = true
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	for host := range hosts {
		result.WorkerHosts = append(result.WorkerHosts, host)
	}
	sort.Strings(result.WorkerHosts)
	for i := range result.Items {
		connection(&result.Items[i], workers)
	}
	return result, nil
}

func connection(d *Device, workers []workerSignal) {
	d.ConnectionStatus = "worker_offline"
	seen := false
	observed := map[string]bool{}
	for _, w := range workers {
		if w.HostID == nil || *w.HostID != d.HostID {
			continue
		}
		if !seen {
			d.WorkerLastSeenAt = nullableStamp(&w.Seen)
			seen = true
		}
		if !w.Live || w.Status != "ready" {
			continue
		}
		if d.ConnectionStatus == "worker_offline" {
			d.ConnectionStatus = "unknown"
		}
		if w.Metrics["adb_status"] != "ready" {
			continue
		}
		devices, ok := w.Metrics["devices"].([]any)
		if !ok {
			continue
		}
		d.ConnectionStatus = "not_connected"
		for _, value := range devices {
			entry, ok := value.(map[string]any)
			if !ok || entry["serial"] != d.Serial {
				continue
			}
			state, ok := entry["state"].(string)
			if ok {
				observed[state] = true
			}
		}
	}
	if observed["device"] {
		d.ConnectionStatus = "connected"
	} else if observed["unauthorized"] {
		d.ConnectionStatus = "unauthorized"
	} else {
		for _, state := range []string{"offline", "recovery", "sideload", "bootloader"} {
			if observed[state] {
				d.ConnectionStatus = "offline"
				break
			}
		}
	}
}

func calendarWindow(observed time.Time, location *time.Location) (time.Time, []DashboardDay) {
	local := observed.In(location)
	// Civil labels use UTC arithmetic: a local midnight can be missing or repeated.
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	first := today.AddDate(0, 0, -6)
	days := make([]DashboardDay, 7)
	for i := range days {
		days[i].Date = first.AddDate(0, 0, i).Format("2006-01-02")
	}
	return firstInstantOfDate(first, location), days
}

// Resolve every adjacent zone period rather than relying on time.Date's ambiguous-midnight choice.
func firstInstantOfDate(civil time.Time, location *time.Location) time.Time {
	date := civil.Format("2006-01-02")
	var earliest, afterSkippedDate time.Time
	consider := func(candidate time.Time) {
		localDate := candidate.In(location).Format("2006-01-02")
		if localDate == date && (earliest.IsZero() || candidate.Before(earliest)) {
			earliest = candidate
		} else if localDate > date && (afterSkippedDate.IsZero() || candidate.Before(afterSkippedDate)) {
			afterSkippedDate = candidate
		}
	}
	limit := civil.Add(48 * time.Hour)
	for cursor := civil.Add(-48 * time.Hour); cursor.Before(limit); {
		local := cursor.In(location)
		_, offset := local.Zone()
		consider(civil.Add(-time.Duration(offset) * time.Second))
		start, end := local.ZoneBounds()
		if !start.IsZero() {
			consider(start)
		}
		if !end.IsZero() {
			consider(end)
		}
		if end.IsZero() || !end.After(cursor) {
			break
		}
		cursor = end
	}
	if !earliest.IsZero() {
		return earliest.UTC()
	}
	// A date-line change can skip a complete local date; its first valid instant is the following day.
	return afterSkippedDate.UTC()
}

func (p *postgresStore) Dashboard(ctx context.Context, zone string) (Dashboard, error) {
	var result Dashboard
	location, err := time.LoadLocation(zone)
	if err != nil {
		return result, err
	}
	tx, err := p.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	var observed time.Time
	if err = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&observed); err != nil {
		return result, err
	}
	start, days := calendarWindow(observed, location)
	result = Dashboard{ObservedAt: stamp(observed), Timezone: zone, WindowStart: stamp(start), WindowEnd: stamp(observed), Days: days}
	rows, err := tx.Query(ctx, `SELECT (finished_at AT TIME ZONE $1)::date::text,status,count(*)
FROM executions WHERE finished_at >= $2 AND finished_at <= $3 AND status IN ('succeeded','failed','cancelled','needs_review')
GROUP BY 1,2`, zone, start, observed)
	if err != nil {
		return result, err
	}
	for rows.Next() {
		var date, status string
		var n int64
		if err = rows.Scan(&date, &status, &n); err != nil {
			rows.Close()
			return result, err
		}
		for i := range result.Days {
			if result.Days[i].Date == date {
				switch status {
				case "succeeded":
					result.Days[i].Succeeded = n
					result.Totals.Succeeded += n
				case "failed":
					result.Days[i].Failed = n
					result.Totals.Failed += n
				case "cancelled":
					result.Days[i].Cancelled = n
					result.Totals.Cancelled += n
				case "needs_review":
					result.Days[i].NeedsReview = n
					result.Totals.NeedsReview += n
				}
			}
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	result.Totals.Finished = result.Totals.Succeeded + result.Totals.Failed + result.Totals.Cancelled + result.Totals.NeedsReview
	return result, tx.Commit(ctx)
}
