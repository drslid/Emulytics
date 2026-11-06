"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale } from "../../lib/i18n";
import {
  isScreenFrameFresh,
  readScreenFrame,
  type ScreenFrameMeta,
} from "../../lib/screen-frame";
import { Icon } from "./icons";

type Frame = ScreenFrameMeta & { url: string };
type Connection = "connecting" | "ready" | "retrying" | "forbidden" | "missing";

export function LiveScreen({
  deviceId,
  name,
}: {
  deviceId: string;
  name?: string;
}) {
  const { t, locale } = useLocale();
  const [frame, setFrame] = useState<Frame | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [visible, setVisible] = useState(true);
  const [clock, setClock] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [fullscreenAvailable, setFullscreenAvailable] = useState(false);
  const viewer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let stopped = false,
      running = false,
      terminal = false;
    let active = document.visibilityState === "visible";
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    let currentUrl: string | null = null,
      pendingUrl: string | null = null,
      currentId = "";
    let pendingImage: HTMLImageElement | null = null;
    setFrame(null);
    setConnection("connecting");
    setVisible(active);
    function clearFrame() {
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      currentUrl = null;
      currentId = "";
      setFrame(null);
    }
    async function refresh() {
      if (stopped || !active || running || terminal) return;
      running = true;
      const request = new AbortController();
      controller = request;
      const timeout = setTimeout(() => request.abort(), 5000);
      try {
        const response = await fetch(
          `/api/control/console/devices/${encodeURIComponent(deviceId)}/screen`,
          {
            credentials: "same-origin",
            cache: "no-store",
            signal: request.signal,
            headers: { Accept: "image/png" },
          },
        );
        if (stopped || !active) return;
        if (response.status === 401 || response.status === 403) {
          terminal = true;
          clearFrame();
          setConnection("forbidden");
          if (response.status === 401) window.location.assign("/connexion");
          return;
        }
        if (response.status === 404) {
          terminal = true;
          clearFrame();
          setConnection("missing");
          return;
        }
        if (!response.ok) {
          setConnection("retrying");
          return;
        }
        const meta = readScreenFrame(response.headers, performance.now());
        if (
          !meta ||
          !isScreenFrameFresh(meta, performance.now()) ||
          response.headers.get("content-type")?.split(";")[0] !== "image/png"
        ) {
          setConnection("retrying");
          return;
        }
        if (meta.frameId === currentId) {
          await response.body?.cancel();
          if (stopped || !active) return;
          setFrame((previous) =>
            previous?.frameId === currentId
              ? { ...previous, ...meta }
              : previous,
          );
          setConnection("ready");
          return;
        }
        const blob = await response.blob();
        if (stopped || !active) return;
        if (blob.size < 8 || blob.size > 16 * 1024 * 1024) {
          setConnection("retrying");
          return;
        }
        const url = URL.createObjectURL(blob);
        pendingUrl = url;
        const image = new Image();
        pendingImage = image;
        image.src = url;
        await image.decode();
        pendingImage = null;
        if (stopped || !active || pendingUrl !== url) {
          URL.revokeObjectURL(url);
          return;
        }
        pendingUrl = null;
        // Decode before replacing the visible bitmap, then release the previous frame.
        const previousUrl = currentUrl;
        currentUrl = url;
        currentId = meta.frameId;
        setFrame({ ...meta, url });
        setConnection("ready");
        setClock(performance.now());
        if (previousUrl) URL.revokeObjectURL(previousUrl);
      } catch {
        if (!stopped && active) setConnection("retrying");
      } finally {
        clearTimeout(timeout);
        if (pendingUrl) URL.revokeObjectURL(pendingUrl);
        pendingUrl = null;
        pendingImage = null;
        controller = null;
        running = false;
        if (!stopped && active && !terminal)
          timer = setTimeout(() => void refresh(), 750);
      }
    }
    function visibility() {
      active = document.visibilityState === "visible";
      setVisible(active);
      if (active) setClock(performance.now());
      clearTimeout(timer);
      if (!active) {
        controller?.abort();
        if (pendingImage) pendingImage.src = "";
        if (pendingUrl) URL.revokeObjectURL(pendingUrl);
        pendingUrl = null;
      } else void refresh();
    }
    document.addEventListener("visibilitychange", visibility);
    const ageTimer = setInterval(() => {
      if (active) setClock(performance.now());
    }, 500);
    void refresh();
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearInterval(ageTimer);
      controller?.abort();
      if (pendingImage) pendingImage.src = "";
      if (pendingUrl) URL.revokeObjectURL(pendingUrl);
      if (currentUrl) URL.revokeObjectURL(currentUrl);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [deviceId]);

  useEffect(() => {
    setFullscreenAvailable(Boolean(viewer.current?.requestFullscreen));
    const changed = () =>
      setFullscreen(document.fullscreenElement === viewer.current);
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === viewer.current)
        await document.exitFullscreen();
      else await viewer.current?.requestFullscreen();
    } catch {
      setFullscreenAvailable(false);
    }
  }
  const fresh =
    visible && connection === "ready" && isScreenFrameFresh(frame, clock);
  const label = !visible
    ? t("En pause")
    : fresh
      ? t("En direct")
      : frame
        ? t("Image figée")
        : connection === "forbidden" || connection === "missing"
          ? t("Écran indisponible")
          : t("Connexion à l’écran…");
  const waiting = connection === "connecting" || connection === "retrying";
  return (
    <div
      className="live-screen"
      ref={viewer}
      role="region"
      aria-label={t("Écran de {name}", { name: name || deviceId })}
    >
      <div className="live-screen-header">
        <div>
          <Icon name="phone" size={18} />
          <strong>{name || deviceId}</strong>
        </div>
        <div className="live-screen-controls">
          <span
            className={`status-badge status-badge--${fresh ? "green" : "amber"}`}
            role="status"
          >
            <span className="status-dot" />
            {label}
          </span>
          <button
            className="text-button"
            disabled={!fullscreenAvailable}
            onClick={() => void toggleFullscreen()}
            aria-label={t(
              fullscreen ? "Quitter le plein écran" : "Plein écran",
            )}
          >
            <span aria-hidden="true">⛶</span>
            {t(fullscreen ? "Quitter le plein écran" : "Plein écran")}
          </button>
        </div>
      </div>
      <div
        className={`live-screen-stage ${frame && !fresh ? "live-screen-stage--stale" : ""}`}
      >
        {frame ? (
          <div className="live-screen-phone">
            <img
              className="live-screen-image"
              src={frame.url}
              alt={t("Écran de {name}", { name: name || deviceId })}
            />
            {!fresh && (
              <div className="live-screen-overlay">
                <Icon name="clock" />
                <strong>{label}</strong>
                <span>
                  {t(
                    !visible
                      ? "Le flux reprendra quand cet onglet sera visible."
                      : "La connexion est interrompue. Nouvelle tentative automatique…",
                  )}
                </span>
              </div>
            )}
          </div>
        ) : (
          <div className="live-screen-placeholder">
            <span className="live-screen-empty-icon">
              <Icon name="phone" size={38} />
            </span>
            <strong>
              {t(waiting ? "Chargement de l’écran…" : "Écran indisponible")}
            </strong>
            <p>
              {t(
                connection === "forbidden"
                  ? "L’accès à cet écran a été révoqué."
                  : connection === "missing"
                    ? "Cet élément n’est plus disponible. Actualisez la page."
                    : "Connexion à l’écran…",
              )}
            </p>
            {waiting && (
              <span className="screen-loading-dot" aria-hidden="true" />
            )}
          </div>
        )}
      </div>
      <div className="live-screen-footer">
        <span>
          {frame
            ? t("Dernière image : {time}", {
                time: new Intl.DateTimeFormat(locale, {
                  timeStyle: "medium",
                }).format(new Date(frame.capturedAt)),
              })
            : t("Environ une image par seconde")}
        </span>
        <span>{t("Affichage en lecture seule")}</span>
      </div>
    </div>
  );
}
