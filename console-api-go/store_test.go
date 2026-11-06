package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestPythonTimestampAndNullContracts(t *testing.T) {
	for _, sample := range []struct {
		nanos int
		want  string
	}{
		{0, "2026-11-06T12:34:56Z"},
		{40000, "2026-11-06T12:34:56.000040Z"},
		{123000000, "2026-11-06T12:34:56.123000Z"},
	} {
		got := stamp(time.Date(2026, 11, 6, 12, 34, 56, sample.nanos, time.UTC))
		if got != sample.want {
			t.Fatalf("got %s want %s", got, sample.want)
		}
	}
	encoded, err := json.Marshal(Device{})
	if err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"active_run_id", "lease_expires_at", "worker_last_seen_at"} {
		if !strings.Contains(string(encoded), `"`+field+`":null`) {
			t.Errorf("missing nullable %s", field)
		}
	}
}

func TestConnectionRequiresFreshMatchingWorkerAndActualADBState(t *testing.T) {
	host, other := "host", "other"
	seen := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)
	makeWorker := func(state string) workerSignal {
		return workerSignal{HostID: &host, Status: "ready", Live: true, Seen: seen, Metrics: map[string]any{"adb_status": "ready", "devices": []any{map[string]any{"serial": "phone", "state": state}}}}
	}
	for _, sample := range []struct{ state, want string }{{"device", "connected"}, {"unauthorized", "unauthorized"}, {"offline", "offline"}, {"recovery", "offline"}, {"bootloader", "offline"}, {"unknown", "not_connected"}} {
		d := Device{HostID: host, Serial: "phone"}
		connection(&d, []workerSignal{makeWorker(sample.state)})
		if d.ConnectionStatus != sample.want {
			t.Errorf("state %s: %s", sample.state, d.ConnectionStatus)
		}
	}
	for _, mode := range []string{"stale", "host", "serial", "missing-metrics", "invalid-devices", "not-ready"} {
		w := makeWorker("device")
		want := "worker_offline"
		switch mode {
		case "stale":
			w.Live = false
		case "host":
			w.HostID = &other
		case "serial":
			w.Metrics["devices"] = []any{map[string]any{"serial": "different", "state": "device"}}
			want = "not_connected"
		case "missing-metrics":
			w.Metrics = nil
			want = "unknown"
		case "invalid-devices":
			w.Metrics["devices"] = "invalid"
			want = "unknown"
		case "not-ready":
			w.Status = "starting"
		}
		d := Device{HostID: host, Serial: "phone"}
		connection(&d, []workerSignal{w})
		if d.ConnectionStatus != want {
			t.Errorf("%s: %s", mode, d.ConnectionStatus)
		}
	}
	d := Device{HostID: host, Serial: "phone"}
	connection(&d, []workerSignal{makeWorker("offline"), makeWorker("device")})
	if d.ConnectionStatus != "connected" {
		t.Fatal("any fresh observation can confirm the exact device")
	}
}

func TestSevenCalendarDaysPreserveDSTAndZeroCounts(t *testing.T) {
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	observed := time.Date(2026, 11, 6, 19, 0, 0, 0, time.UTC)
	start, days := calendarWindow(observed, zone)
	if !start.Equal(time.Date(2026, 10, 31, 4, 0, 0, 0, time.UTC)) {
		t.Fatalf("incorrect DST start %s", start)
	}
	if len(days) != 7 || days[0].Date != "2026-10-31" || days[6].Date != "2026-11-06" {
		t.Fatalf("incorrect days %+v", days)
	}
	for _, day := range days {
		if day.Counts != (Counts{}) {
			t.Fatal("empty days must contain real numeric zeroes")
		}
	}
	// Spring transition: subtracting six 24-hour durations would land on the preceding local date.
	start, days = calendarWindow(time.Date(2026, 3, 13, 18, 0, 0, 0, time.UTC), zone)
	if !start.Equal(time.Date(2026, 3, 7, 5, 0, 0, 0, time.UTC)) || days[6].Date != "2026-03-13" {
		t.Fatalf("incorrect spring DST start %s", start)
	}
}

func TestMidnightTransitionsUseCivilDatesAndEarliestValidInstant(t *testing.T) {
	for _, sample := range []struct{ zone, observed, first, last, start string }{
		{"America/Santiago", "2026-09-06T16:00:00Z", "2026-08-31", "2026-09-06", "2026-08-31T04:00:00Z"},
		{"America/Santiago", "2026-09-12T16:00:00Z", "2026-09-06", "2026-09-12", "2026-09-06T04:00:00Z"},
		{"America/Havana", "2026-11-07T16:00:00Z", "2026-11-01", "2026-11-07", "2026-11-01T04:00:00Z"},
		{"Pacific/Apia", "2012-01-04T12:00:00Z", "2011-12-30", "2012-01-05", "2011-12-30T10:00:00Z"},
	} {
		location, err := time.LoadLocation(sample.zone)
		if err != nil {
			t.Fatal(err)
		}
		observed, _ := time.Parse(time.RFC3339, sample.observed)
		start, days := calendarWindow(observed, location)
		expected, _ := time.Parse(time.RFC3339, sample.start)
		if days[0].Date != sample.first || days[6].Date != sample.last || !start.Equal(expected) {
			t.Errorf("%s %s: start %s, days %s..%s", sample.zone, sample.observed, start, days[0].Date, days[6].Date)
		}
	}
}
