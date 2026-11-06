package main

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"strings"
	"sync"
	"testing"
)

const handlerTestOrigin = "http://localhost:3100"
const handlerTestUser = `{"user":{"id":"test-user","active":true,"permissions":["devices.read","monitor.read"]}}`

type handlerTestStore struct {
	mu            sync.Mutex
	calls         []string
	limit, offset int64
	zone          string
	err           error
}

func (s *handlerTestStore) Summary(context.Context) (Summary, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, "summary")
	return Summary{DevicesTotal: 2, WorkflowsTotal: 1, RunsTotal: 10, RunsSucceeded: 6}, s.err
}
func (s *handlerTestStore) Fleet(_ context.Context, limit, offset int64) (FleetPage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, "fleet")
	s.limit, s.offset = limit, offset
	return FleetPage{Items: []Device{}, WorkerHosts: []string{}, Limit: limit, Offset: offset}, s.err
}
func (s *handlerTestStore) Dashboard(_ context.Context, zone string) (Dashboard, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, "dashboard")
	s.zone = zone
	return Dashboard{Timezone: zone}, s.err
}
func (s *handlerTestStore) Ping(context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, "ping")
	return s.err
}
func (s *handlerTestStore) called() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string{}, s.calls...)
}

type handlerAuthObservation struct {
	method, path string
	headers      http.Header
}

func handlerFixture(t *testing.T, status int, body string) (*handlerTestStore, http.Handler, <-chan handlerAuthObservation) {
	t.Helper()
	observed := make(chan handlerAuthObservation, 64)
	auth := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		observed <- handlerAuthObservation{r.Method, r.URL.Path, r.Header.Clone()}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(auth.Close)
	store := &handlerTestStore{}
	return store, newHandler(store, auth.URL+"/", handlerTestOrigin, auth.Client()), observed
}

func handlerCall(handler http.Handler, method, path, cookie, origin string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, nil)
	if cookie != "" {
		request.Header.Set("Cookie", cookie)
	}
	if origin != "" {
		request.Header.Set("Origin", origin)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func handlerAssertStatus(t *testing.T, response *httptest.ResponseRecorder, status int) {
	t.Helper()
	if response.Code != status {
		t.Fatalf("HTTP %d, expected %d: %s", response.Code, status, response.Body.String())
	}
	if response.Header().Get("X-Emulytix-Backend") != "go" {
		t.Fatal("the Go backend marker must be present on every response")
	}
	if response.Header().Get("Cache-Control") != "private, no-store" {
		t.Fatal("private responses must not be cached")
	}
	if !json.Valid(response.Body.Bytes()) {
		t.Fatal("the API must return JSON for success and errors")
	}
}

func TestHandlerDelegatesSessionOnlyToTheExactAuthenticationRoute(t *testing.T) {
	store, handler, observed := handlerFixture(t, http.StatusOK, handlerTestUser)
	request := httptest.NewRequest(http.MethodGet, "/console/summary", nil)
	request.Header.Set("Cookie", "other=private; emulytix_session=test_session; emulytix_challenge=challenge")
	request.Header.Set("Authorization", "Bearer untrusted")
	request.Header.Set("X-User", "administrator")
	request.Header.Set("X-Emulytix-Backend", "python")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	handlerAssertStatus(t, response, http.StatusOK)
	auth := <-observed
	if auth.method != http.MethodGet || auth.path != "/auth/me" {
		t.Fatalf("unexpected authentication request: %s %s", auth.method, auth.path)
	}
	if auth.headers.Get("Cookie") != "emulytix_session=test_session" {
		t.Fatalf("only the session cookie may reach authentication: %q", auth.headers.Get("Cookie"))
	}
	for _, header := range []string{"Authorization", "X-User", "X-Emulytix-Backend"} {
		if auth.headers.Get(header) != "" {
			t.Fatalf("untrusted identity header forwarded: %s", header)
		}
	}
	if !reflect.DeepEqual(store.called(), []string{"summary"}) {
		t.Fatalf("unexpected store calls: %v", store.called())
	}
	var result Summary
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil || result.DevicesTotal != 2 || result.RunsSucceeded != 6 {
		t.Fatalf("summary was not preserved: %s", response.Body.String())
	}
}

func TestHandlerMissingOrInvalidSessionCannotUseBearerOrQueryIdentity(t *testing.T) {
	for _, cookie := range []string{"", "emulytix_challenge=challenge", "emulytix_session=", "emulytix_session=" + strings.Repeat("x", 129)} {
		t.Run(cookie, func(t *testing.T) {
			store, handler, observed := handlerFixture(t, http.StatusOK, handlerTestUser)
			request := httptest.NewRequest(http.MethodGet, "/console/fleet?limit=bad&token=pretend&user=admin", nil)
			request.Header.Set("Authorization", "Bearer pretend-jwt")
			request.Header.Set("X-User", "administrator")
			request.Header.Set("Cookie", cookie)
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			handlerAssertStatus(t, response, http.StatusUnauthorized)
			if len(store.called()) != 0 || len(observed) != 0 {
				t.Fatal("an invalid session must not reach authentication or the database")
			}
		})
	}
}

func TestHandlerRepeatedSessionCookieUsesTheLastValue(t *testing.T) {
	_, handler, observed := handlerFixture(t, http.StatusOK, handlerTestUser)
	response := handlerCall(handler, http.MethodGet, "/console/summary", "emulytix_session=first; emulytix_session=last", "")
	handlerAssertStatus(t, response, http.StatusOK)
	if cookie := (<-observed).headers.Get("Cookie"); cookie != "emulytix_session=last" {
		t.Fatalf("wrong duplicate-cookie precedence: %q", cookie)
	}
}

func TestHandlerRejectsAuthenticationFailuresBeforeQueryValidation(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden} {
		store, handler, _ := handlerFixture(t, status, `{"detail":"private upstream information"}`)
		for _, path := range []string{"/console/fleet?limit=bad", "/console/dashboard?timezone=Mars%2FOlympus"} {
			response := handlerCall(handler, http.MethodGet, path, "emulytix_session=session", "")
			handlerAssertStatus(t, response, status)
			if strings.Contains(response.Body.String(), "private") || len(store.called()) != 0 {
				t.Fatal("authentication errors must be generic and precede data access")
			}
		}
	}
}

func TestHandlerPermissionsAreCheckedPerRoute(t *testing.T) {
	for _, entry := range []struct {
		permission, path string
		status           int
	}{
		{"devices.read", "/console/fleet", 200},
		{"devices.read", "/console/summary", 403},
		{"devices.read", "/console/dashboard", 403},
		{"monitor.read", "/console/summary", 200},
		{"monitor.read", "/console/dashboard", 200},
		{"monitor.read", "/console/fleet", 403},
		{"users.manage", "/console/fleet", 403},
	} {
		t.Run(entry.permission+entry.path, func(t *testing.T) {
			body := `{"user":{"id":"test-user","active":true,"permissions":["` + entry.permission + `"]}}`
			store, handler, _ := handlerFixture(t, 200, body)
			response := handlerCall(handler, http.MethodGet, entry.path, "emulytix_session=session", "")
			handlerAssertStatus(t, response, entry.status)
			if entry.status == 403 && len(store.called()) != 0 {
				t.Fatal("forbidden callers must not access data")
			}
		})
	}
}

func TestHandlerInactiveUserCannotAccessData(t *testing.T) {
	store, handler, _ := handlerFixture(t, 200, `{"user":{"id":"test-user","active":false,"permissions":["devices.read","monitor.read"]}}`)
	handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/console/summary", "emulytix_session=session", ""), 401)
	if len(store.called()) != 0 {
		t.Fatal("an inactive account must not access data")
	}
}

func TestHandlerMalformedOrUnavailableAuthenticationFailsClosed(t *testing.T) {
	for _, entry := range []struct {
		name, body string
		status     int
	}{
		{"unavailable", `{"detail":"private auth database"}`, 500},
		{"empty", "", 200},
		{"invalid", "not JSON", 200},
		{"null", "null", 200},
		{"no user", `{}`, 200},
		{"no identity", `{"user":{"active":true,"permissions":["monitor.read"]}}`, 200},
		{"bad permissions", `{"user":{"id":"test-user","active":true,"permissions":"monitor.read"}}`, 200},
		{"trailing payload", handlerTestUser + `{}`, 200},
		{"oversized", `{"user":{"id":"test-user","active":true,"permissions":["monitor.read"]},"padding":"` + strings.Repeat("x", 32768) + `"}`, 200},
	} {
		t.Run(entry.name, func(t *testing.T) {
			store, handler, _ := handlerFixture(t, entry.status, entry.body)
			response := handlerCall(handler, http.MethodGet, "/console/summary", "emulytix_session=session", "")
			handlerAssertStatus(t, response, 503)
			if strings.Contains(response.Body.String(), "private") || len(store.called()) != 0 {
				t.Fatal("unverified identity must not disclose upstream details or access data")
			}
		})
	}
}

func TestHandlerNeverFollowsAuthenticationRedirects(t *testing.T) {
	redirected := make(chan struct{}, 1)
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		redirected <- struct{}{}
		_, _ = w.Write([]byte(handlerTestUser))
	}))
	t.Cleanup(target.Close)
	auth := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, http.StatusFound) }))
	t.Cleanup(auth.Close)
	store := &handlerTestStore{}
	handler := newHandler(store, auth.URL, handlerTestOrigin, auth.Client())
	handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/console/summary", "emulytix_session=session", ""), 503)
	if len(redirected) != 0 || len(store.called()) != 0 {
		t.Fatal("authentication redirects must not be followed or grant access")
	}
}

func TestHandlerUnreachableAuthenticationNeverGrantsDataAccess(t *testing.T) {
	auth := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	client := auth.Client()
	auth.Close()
	store := &handlerTestStore{}
	handler := newHandler(store, auth.URL, handlerTestOrigin, client)
	response := handlerCall(handler, http.MethodGet, "/console/fleet", "emulytix_session=session", "")
	handlerAssertStatus(t, response, 503)
	if len(store.called()) != 0 || strings.Contains(response.Body.String(), auth.URL) {
		t.Fatal("authentication transport failures must not grant access or disclose addresses")
	}
}

func TestHandlerClosesMethodsPathsAndForeignOrigins(t *testing.T) {
	store, handler, observed := handlerFixture(t, 200, handlerTestUser)
	for _, method := range []string{http.MethodPost, http.MethodPatch, http.MethodDelete, http.MethodHead, http.MethodOptions} {
		for _, path := range []string{"/console/summary", "/console/fleet", "/console/dashboard"} {
			response := handlerCall(handler, method, path, "emulytix_session=session", handlerTestOrigin)
			handlerAssertStatus(t, response, 405)
			if response.Header().Get("Allow") != "GET" {
				t.Fatal("closed methods must advertise the sole supported method")
			}
		}
	}
	for _, path := range []string{"/console/summary/", "/console/fleet/extra", "/console/dashboard/extra", "/auth/me", "/devices", "/runs", "/console/not-here"} {
		handlerAssertStatus(t, handlerCall(handler, http.MethodGet, path, "emulytix_session=session", handlerTestOrigin), 404)
	}
	for _, origin := range []string{"https://invalid.test", "http://localhost:3100.invalid.test", "null"} {
		handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/console/fleet", "emulytix_session=session", origin), 403)
	}
	if len(store.called()) != 0 || len(observed) != 0 {
		t.Fatal("invalid routes, methods and origins must stop before authentication and data access")
	}
	handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/console/fleet", "emulytix_session=session", handlerTestOrigin), 200)
}

func TestHandlerFleetPaginationMatchesIntegerQuerySemantics(t *testing.T) {
	for _, entry := range []struct {
		query         string
		limit, offset int64
	}{
		{"", 100, 0},
		{"?limit=1&offset=0", 1, 0},
		{"?limit=100&offset=123", 100, 123},
		{"?limit=01&offset=%2B2", 1, 2},
		{"?limit=%203%20&offset=4.00", 3, 4},
		{"?limit=1_0&offset=-0", 10, 0},
		{"?limit=9.0&offset=0.0", 9, 0},
		{"?limit=bad&limit=2&offset=bad&offset=7", 2, 7},
		{"?offset=9223372036854775807", 100, math.MaxInt64},
	} {
		t.Run(entry.query, func(t *testing.T) {
			store, handler, _ := handlerFixture(t, 200, handlerTestUser)
			response := handlerCall(handler, http.MethodGet, "/console/fleet"+entry.query, "emulytix_session=session", "")
			handlerAssertStatus(t, response, 200)
			if store.limit != entry.limit || store.offset != entry.offset {
				t.Fatalf("wrong fleet arguments: limit %d offset %d", store.limit, store.offset)
			}
		})
	}
}

func TestHandlerInvalidPaginationNeverReachesTheStore(t *testing.T) {
	for _, query := range []string{"?limit=0", "?limit=101", "?limit=-1", "?offset=-1", "?limit=1.5", "?limit=5e0", "?limit=", "?limit=_4", "?offset=9223372036854775808", "?limit=2&limit=bad", "?offset=2&offset=bad", "?limit=١٢"} {
		t.Run(query, func(t *testing.T) {
			store, handler, _ := handlerFixture(t, 200, handlerTestUser)
			response := handlerCall(handler, http.MethodGet, "/console/fleet"+query, "emulytix_session=session", "")
			handlerAssertStatus(t, response, 422)
			if len(store.called()) != 0 {
				t.Fatal("invalid pagination must not reach PostgreSQL")
			}
		})
	}
}

func TestHandlerDashboardUsesValidatedCalendarTimezone(t *testing.T) {
	for _, entry := range []struct{ query, expected string }{
		{"", "UTC"},
		{"?timezone=UTC", "UTC"},
		{"?timezone=" + url.QueryEscape("Europe/Paris"), "Europe/Paris"},
		{"?timezone=" + url.QueryEscape("America/New_York"), "America/New_York"},
		{"?timezone=invalid&timezone=UTC", "UTC"},
	} {
		store, handler, _ := handlerFixture(t, 200, handlerTestUser)
		handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/console/dashboard"+entry.query, "emulytix_session=session", ""), 200)
		if store.zone != entry.expected {
			t.Fatalf("timezone %q, expected %q", store.zone, entry.expected)
		}
	}
	for _, zone := range []string{"", "Local", "Mars/Olympus", "../../etc/passwd", strings.Repeat("x", 129)} {
		store, handler, _ := handlerFixture(t, 200, handlerTestUser)
		handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/console/dashboard?timezone="+url.QueryEscape(zone), "emulytix_session=session", ""), 422)
		if len(store.called()) != 0 {
			t.Fatal("an invalid timezone must not reach the database")
		}
	}
}

func TestHandlerDataErrorsAreGenericAndDoNotLeakDatabaseConfiguration(t *testing.T) {
	for _, path := range []string{"/console/summary", "/console/fleet", "/console/dashboard"} {
		store, handler, _ := handlerFixture(t, 200, handlerTestUser)
		store.err = errors.New("postgres://private-user:private-password@internal:5432/console")
		response := handlerCall(handler, http.MethodGet, path, "emulytix_session=session", "")
		handlerAssertStatus(t, response, 503)
		for _, value := range []string{"postgres", "private", "password", "internal"} {
			if strings.Contains(response.Body.String(), value) {
				t.Fatal("database errors must not disclose internal configuration")
			}
		}
	}
}

func TestHandlerHealthChecksTheDatabaseWithoutAuthentication(t *testing.T) {
	store, handler, observed := handlerFixture(t, 200, handlerTestUser)
	handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/health", "", ""), 200)
	if !reflect.DeepEqual(store.called(), []string{"ping"}) || len(observed) != 0 {
		t.Fatal("health must check the database independently of authentication")
	}
	store.err = errors.New("private database address")
	handlerAssertStatus(t, handlerCall(handler, http.MethodGet, "/health", "", ""), 503)
}
