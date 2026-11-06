package main

import (
	"context"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)
	if len(os.Args) == 2 && os.Args[1] == "--healthcheck" {
		client := http.Client{Timeout: 2 * time.Second}
		response, err := client.Get("http://127.0.0.1:8020/health")
		if err != nil {
			os.Exit(1)
		}
		response.Body.Close()
		if response.StatusCode != 200 {
			os.Exit(1)
		}
		return
	}
	dsn, authURL, origin := os.Getenv("EMULYTIX_DATABASE_URL"), os.Getenv("EMULYTIX_AUTH_INTERNAL_URL"), os.Getenv("EMULYTIX_PUBLIC_ORIGIN")
	parsed, err := url.Parse(authURL)
	if dsn == "" || origin == "" || err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || parsed.Path != "" && parsed.Path != "/" || parsed.Scheme != "http" && parsed.Scheme != "https" {
		logger.Error("configuration.invalid")
		os.Exit(1)
	}
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		logger.Error("database.configuration_invalid")
		os.Exit(1)
	}
	config.MaxConns = 4
	config.MinConns = 0
	config.ConnConfig.ConnectTimeout = 3 * time.Second
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		logger.Error("database.unavailable")
		os.Exit(1)
	}
	defer pool.Close()
	probe, cancel := context.WithTimeout(ctx, 5*time.Second)
	err = pool.Ping(probe)
	cancel()
	if err != nil {
		logger.Error("database.unavailable")
		os.Exit(1)
	}
	store := &postgresStore{pool: pool}
	client := &http.Client{Timeout: 3 * time.Second, Transport: &http.Transport{MaxIdleConns: 16, MaxIdleConnsPerHost: 4, IdleConnTimeout: 60 * time.Second}}
	address := os.Getenv("EMULYTIX_LISTEN_ADDR")
	if address == "" {
		address = ":8020"
	}
	server := &http.Server{Addr: address, Handler: newHandler(store, authURL, origin, client), ReadHeaderTimeout: 3 * time.Second, ReadTimeout: 5 * time.Second, WriteTimeout: 12 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16384}
	if strings.EqualFold(os.Getenv("EMULYTIX_TELEMETRY_ENABLED"), "true") {
		go reportHeartbeat(ctx, pool, logger)
	}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	logger.Info("api.started", "routes_migrated", 3)
	if err = server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		logger.Error("http.unavailable")
		os.Exit(1)
	}
}

func reportHeartbeat(ctx context.Context, pool *pgxpool.Pool, logger *slog.Logger) {
	identity, err := os.Hostname()
	if err != nil || identity == "" {
		identity = "go-api"
	}
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		call, cancel := context.WithTimeout(ctx, 2*time.Second)
		_, err = pool.Exec(call, `INSERT INTO service_heartbeats(component,instance_id,status,metrics)
VALUES('api-go',$1,'ready','{"routes_migrated":3}'::jsonb)
ON CONFLICT(component,instance_id) DO UPDATE SET status='ready',metrics=EXCLUDED.metrics,last_seen_at=clock_timestamp()`, identity)
		cancel()
		if err != nil && ctx.Err() == nil {
			logger.Warn("service.heartbeat_unavailable", "component", "api-go")
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
