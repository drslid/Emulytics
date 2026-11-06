package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
	_ "time/tzdata"
)

type dataStore interface {
	Summary(context.Context) (Summary, error)
	Fleet(context.Context, int64, int64) (FleetPage, error)
	Dashboard(context.Context, string) (Dashboard, error)
	Ping(context.Context) error
}

type apiServer struct {
	store           dataStore
	authURL, origin string
	client          *http.Client
}

var sessionPattern = regexp.MustCompile(`^[A-Za-z0-9_.~-]{1,128}$`)
var integerPattern = regexp.MustCompile(`^[+-]?[0-9](?:_?[0-9])*(?:\.0+)?$`)

func newHandler(store dataStore, authURL, origin string, client *http.Client) http.Handler {
	return &apiServer{store: store, authURL: strings.TrimRight(authURL, "/") + "/auth/me", origin: origin, client: client}
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func reject(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func (s *apiServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
	w.Header().Set("X-Emulytix-Backend", "go")
	permission := "monitor.read"
	switch r.URL.Path {
	case "/health", "/console/summary", "/console/dashboard":
	case "/console/fleet":
		permission = "devices.read"
	default:
		reject(w, 404, "Route indisponible")
		return
	}
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", "GET")
		reject(w, 405, "Méthode indisponible")
		return
	}
	if r.URL.Path == "/health" {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		if s.store.Ping(ctx) != nil {
			reject(w, 503, "Service indisponible")
			return
		}
		writeJSON(w, 200, map[string]string{"status": "ok"})
		return
	}
	if origin := r.Header.Get("Origin"); origin != "" && origin != s.origin {
		reject(w, 403, "Origine refusée")
		return
	}
	if status := s.authorize(r, permission); status != 0 {
		detail := "Authentification indisponible"
		if status == 401 {
			detail = "Connexion requise"
		} else if status == 403 {
			detail = "Droits insuffisants"
		}
		reject(w, status, detail)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	var value any
	var err error
	switch r.URL.Path {
	case "/console/summary":
		value, err = s.store.Summary(ctx)
	case "/console/fleet":
		limit, valid := integerQuery(r, "limit", 100, 1, 100)
		if !valid {
			reject(w, 422, "Pagination invalide")
			return
		}
		offset, valid := integerQuery(r, "offset", 0, 0, 1<<63-1)
		if !valid {
			reject(w, 422, "Pagination invalide")
			return
		}
		value, err = s.store.Fleet(ctx, limit, offset)
	case "/console/dashboard":
		zone, exists := lastQuery(r, "timezone")
		if !exists {
			zone = "UTC"
		}
		if len(zone) == 0 || len(zone) > 128 || zone == "Local" {
			reject(w, 422, "Fuseau horaire invalide")
			return
		}
		if _, e := time.LoadLocation(zone); e != nil {
			reject(w, 422, "Fuseau horaire invalide")
			return
		}
		value, err = s.store.Dashboard(ctx, zone)
	}
	if err != nil {
		reject(w, 503, "Mesures indisponibles")
		return
	}
	writeJSON(w, 200, value)
}

func lastQuery(r *http.Request, key string) (string, bool) {
	values, exists := r.URL.Query()[key]
	if !exists || len(values) == 0 {
		return "", false
	}
	return values[len(values)-1], true
}

func integerQuery(r *http.Request, key string, fallback, min, max int64) (int64, bool) {
	value, exists := lastQuery(r, key)
	if !exists {
		return fallback, true
	}
	value = strings.TrimSpace(value)
	if len(value) > 128 || !integerPattern.MatchString(value) {
		return 0, false
	}
	value = strings.SplitN(strings.ReplaceAll(value, "_", ""), ".", 2)[0]
	result, err := strconv.ParseInt(value, 10, 64)
	return result, err == nil && result >= min && result <= max
}

func (s *apiServer) authorize(r *http.Request, permission string) int {
	// Cookie precedence follows Python's last-value parser; caller-supplied identity headers are ignored.
	token := ""
	for _, cookie := range r.Cookies() {
		if cookie.Name == "emulytix_session" {
			token = cookie.Value
		}
	}
	if !sessionPattern.MatchString(token) {
		return 401
	}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, s.authURL, nil)
	if err != nil {
		return 503
	}
	request.Header.Set("Accept", "application/json")
	request.AddCookie(&http.Cookie{Name: "emulytix_session", Value: token})
	// Apply redirect refusal even when a caller supplies its own transport/client.
	client := *s.client
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := client.Do(request)
	if err != nil {
		return 503
	}
	defer response.Body.Close()
	if response.StatusCode == 401 || response.StatusCode == 403 {
		return response.StatusCode
	}
	if response.StatusCode != 200 {
		return 503
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, 32769))
	if err != nil || len(body) > 32768 {
		return 503
	}
	var payload struct {
		User *struct {
			ID          string   `json:"id"`
			Active      bool     `json:"active"`
			Permissions []string `json:"permissions"`
		} `json:"user"`
	}
	if json.Unmarshal(body, &payload) != nil || payload.User == nil || payload.User.ID == "" {
		return 503
	}
	if !payload.User.Active {
		return 401
	}
	for _, allowed := range payload.User.Permissions {
		if allowed == permission {
			return 0
		}
	}
	return 403
}
