"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/client-api";
import { useT } from "../../lib/i18n";
import { Icon } from "./icons";
import { Dialog, ErrorNotice } from "./shared";

type ReleaseStatus = {
  installed_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  can_install: boolean;
  release_url: string | null;
  state: "idle" | "queued" | "installing" | "installed" | "failed";
  target_version: string | null;
  error: string | null;
  check_failed: boolean;
};

const updatesPath = "console/updates";
const installGuide = "https://drslid.github.io/Emulytics/getting-started/install/";
const releaseLink = /^https:\/\/github\.com\/drslid\/Emulytics\/releases\/tag\/v?\d+\.\d+\.\d+$/;

export function useReleaseUpdates(enabled: boolean) {
  const [status, setStatus] = useState<ReleaseStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkFailed, setCheckFailed] = useState(false);
  const [awaitingStatus, setAwaitingStatus] = useState(false);
  const [installRejected, setInstallRejected] = useState(false);
  const [requestedVersion, setRequestedVersion] = useState<string | null>(null);
  const nextRequest = useRef(0);
  const activeCheck = useRef<number | null>(null);
  const posting = useRef(false);
  const updating = awaitingStatus || status?.state === "queued" || status?.state === "installing";

  const check = useCallback(async () => {
    if (!enabled || posting.current || activeCheck.current !== null) return;
    const request = ++nextRequest.current;
    activeCheck.current = request;
    setChecking(true);
    try {
      const response = await api<ReleaseStatus>(updatesPath);
      if (activeCheck.current !== request) return;
      setStatus(response);
      setCheckFailed(false);
      setAwaitingStatus(false);
    } catch {
      if (activeCheck.current === request) setCheckFailed(true);
    } finally {
      if (activeCheck.current === request) {
        activeCheck.current = null;
        setChecking(false);
      }
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    const checkVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    checkVisible();
    const timer = setInterval(checkVisible, updating ? 5000 : 60_000);
    document.addEventListener("visibilitychange", checkVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", checkVisible);
    };
  }, [enabled, check, updating]);

  const canInstall = !!status?.can_install && status.update_available && !status.check_failed && !updating && !checkFailed;

  async function install(version: string) {
    if (!enabled || !canInstall || status?.latest_version !== version || posting.current) return;
    posting.current = true;
    activeCheck.current = null;
    setChecking(false);
    setAwaitingStatus(true);
    setInstallRejected(false);
    setRequestedVersion(version);
    try {
      await api(updatesPath, { version });
    } catch (failure) {
      // A lost response may mean the request reached the updater. Read its state before allowing a retry.
      if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500) {
        setInstallRejected(true);
        setRequestedVersion(null);
      }
    } finally {
      posting.current = false;
      void check();
    }
  }

  return { status, checking, checkFailed, updating, requestedVersion, installRejected, canInstall, check, install };
}

export type ReleaseUpdates = ReturnType<typeof useReleaseUpdates>;

export function ReleaseUpdateNotice({ updates }: { updates: ReleaseUpdates }) {
  const t = useT();
  const version = updates.status?.latest_version;
  if (!updates.status?.update_available || !version || updates.updating) return null;
  return <div className="notice notice--info release-update-notice" role="status">
    <Icon name="refresh" size={18} />
    <span>{t("Emulytics {version} est disponible.", { version })}</span>
    <a href="/configuration#mises-a-jour">{t("Voir la mise à jour")}</a>
  </div>;
}

export function ReleaseUpdatePanel({ updates }: { updates: ReleaseUpdates }) {
  const t = useT();
  const { status, updating, checking, checkFailed, requestedVersion, installRejected, canInstall } = updates;
  const [confirmVersion, setConfirmVersion] = useState<string | null>(null);
  const version = status?.latest_version;
  const releaseUrl = status?.release_url && releaseLink.test(status.release_url) ? status.release_url : null;
  const checkingUnavailable = checkFailed || !!status?.check_failed;
  const installedVersion = status?.installed_version;
  const installed = status?.state === "installed" && !!installedVersion && requestedVersion === installedVersion;
  const failureMessage = status?.error === "active_runs"
    ? t("Attendez la fin des exécutions en cours, puis relancez la mise à jour.")
    : status?.error === "dirty_checkout" || status?.error === "diverged_checkout"
      ? t("Vérifiez les modifications Git sur l’hôte avant de relancer la mise à jour.")
      : t("L’installation a échoué. Consultez les journaux sur l’hôte ou réessayez.");

  return <section id="mises-a-jour" className="surface release-updates" aria-labelledby="release-updates-heading">
    <h2 id="release-updates-heading">{t("Mises à jour")}</h2>
    {status && <dl className="release-versions">
      <div><dt>{t("Version installée")}</dt><dd><bdi>{installedVersion || t("Indisponible")}</bdi></dd></div>
      <div><dt>{t("Dernière version publiée")}</dt><dd><bdi>{version || t("Indisponible")}</bdi></dd></div>
    </dl>}
    {updating ? <p className="notice notice--info" role="status">
      {checkFailed ? t("En attente de la reconnexion à la console…") : t("Installation de la mise à jour…")}
    </p> : <>
      {checkingUnavailable && <ErrorNotice message={t("Impossible de vérifier les mises à jour.")} />}
      {(status?.state === "failed" || installRejected) &&
        <ErrorNotice message={installRejected ? t("La mise à jour n’a pas pu être lancée.") : failureMessage} />}
      {installed ? <p className="notice notice--success" role="status">{t("Emulytics {version} est installé.", { version: installedVersion })}</p>
        : status?.update_available && version ? <p role="status">{t("Emulytics {version} est disponible.", { version })}</p>
        : status && installedVersion && version && !checkingUnavailable ? <p role="status">{t("Emulytics est à jour.")}</p>
        : !status && !checkingUnavailable ? <p role="status">{t("Recherche d’une nouvelle version…")}</p> : null}
      {status?.update_available && !status.can_install && !checkingUnavailable &&
        <p>{t("Installez la mise à jour depuis l’hôte.")} <a href={installGuide}>{t("Guide d’installation")}</a></p>}
    </>}
    <div className="release-update-actions">
      {canInstall && version && <button type="button" className="button button--primary" onClick={() => setConfirmVersion(version)}>{t("Mettre à jour")}</button>}
      {installed && <button type="button" className="button button--secondary" onClick={() => window.location.reload()}>{t("Recharger la console")}</button>}
      <button type="button" className="text-button" onClick={() => void updates.check()} disabled={checking || updating}>
        <Icon name="refresh" size={17} />{t("Vérifier les mises à jour")}
      </button>
      {releaseUrl && <a className="text-button" href={releaseUrl} target="_blank" rel="noreferrer">{t("Notes de version")}<Icon name="arrow" size={16} /></a>}
    </div>
    {confirmVersion && <Dialog title={t("Installer Emulytics {version}", { version: confirmVersion })}
      description={t("La console sera temporairement indisponible pendant le redémarrage.")} onClose={() => setConfirmVersion(null)}>
      <div className="dialog-form">
        <div className="dialog-footer">
          <button type="button" className="button button--secondary" onClick={() => setConfirmVersion(null)}>{t("Annuler")}</button>
          <button type="button" className="button button--primary" disabled={!canInstall || version !== confirmVersion} onClick={() => {
            setConfirmVersion(null);
            void updates.install(confirmVersion);
          }}>{t("Mettre à jour")}</button>
        </div>
      </div>
    </Dialog>}
  </section>;
}
