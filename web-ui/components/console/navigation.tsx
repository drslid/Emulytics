"use client";

import { useEffect, useId, useState } from "react";
import type { User, View } from "../../lib/console-types";
import { useT } from "../../lib/i18n";
import { Icon } from "./icons";
import { Dialog } from "./shared";

const navigation = [
  {
    id: "control", label: "Pilotage", items: [
      { id: "overview", href: "/", label: "Tableau de bord", icon: "overview" as const },
      { id: "devices", href: "/telephones", label: "Appareils", icon: "phone" as const }
    ]
  },
  {
    id: "automation", label: "Automatisation", items: [
      { id: "workflows", href: "/automatisations", label: "Parcours", icon: "workflow" as const },
      { id: "activity", href: "/activite", label: "Exécutions", icon: "activity" as const },
      { id: "schedules", href: "/planifications", label: "Planifications", icon: "clock" as const }
    ]
  },
  {
    id: "supervision", label: "Supervision", items: [
      { id: "monitor", href: "/monitoring", label: "Monitoring", icon: "activity" as const },
      { id: "logs", href: "/journal", label: "Journal", icon: "archive" as const }
    ]
  },
  {
    id: "administration", label: "Administration", items: [
      { id: "configuration", href: "/configuration", label: "Configuration", icon: "settings" as const },
      { id: "users", href: "/utilisateurs", label: "Utilisateurs", icon: "users" as const }
    ]
  }
];

type NavigationProps = { user: User; view: View; needsReviewCount?: number };

function NavigationLinks({ user, view, needsReviewCount = 0, idPrefix, mobile = false, onNavigate }: NavigationProps & {
  idPrefix: string; mobile?: boolean; onNavigate?: () => void;
}) {
  const t = useT();
  return <nav className={mobile ? "main-navigation mobile-navigation-links tw:grid tw:grid-cols-1 tw:gap-5 tw:p-5" : "main-navigation desktop-navigation"} aria-label={t("Navigation principale")}>
    {navigation.map(group => {
      const items = group.items.filter(item => item.id !== "users" && item.id !== "logs" || user.permissions?.includes(item.id === "users" ? "users.manage" : "logs.read"));
      if (!items.length) return null;
      const labelId = `${idPrefix}-${group.id}`;
      return <div key={group.id} className="nav-section" data-theme={group.id} role="group" aria-labelledby={labelId}>
        <p className="nav-section-title" id={labelId}>{t(group.label)}</p>
        <div className="nav-section-items">{items.map(item => <a key={item.id} href={item.href} aria-current={view === item.id ? "page" : undefined} className={view === item.id ? "nav-item nav-item--active" : "nav-item"} onClick={onNavigate}>
          <Icon name={item.icon} /><span>{t(item.label)}</span>
          {item.id === "activity" && needsReviewCount > 0 && <span className="nav-count">{needsReviewCount}</span>}
        </a>)}</div>
      </div>;
    })}
  </nav>;
}

export function ConsoleNavigation({ user, view, needsReviewCount = 0 }: NavigationProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const id = useId();
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 901px)");
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    closeOnDesktop();
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);
  return <>
    <NavigationLinks user={user} view={view} needsReviewCount={needsReviewCount} idPrefix={`${id}-desktop`} />
    <button type="button" className="icon-button mobile-navigation-trigger" aria-label={t("Navigation principale")} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
      <Icon name="menu" size={24} />
    </button>
    {open && <Dialog title={t("Navigation principale")} className="console-dialog--navigation" onClose={() => setOpen(false)}>
      <NavigationLinks user={user} view={view} needsReviewCount={needsReviewCount} idPrefix={`${id}-mobile`} mobile onNavigate={() => setOpen(false)} />
    </Dialog>}
  </>;
}
