import { resolveLocale, serverT } from "../../lib/i18n-server";
import { localeInfo, type Translate } from "../../lib/i18n-core";
import { LanguageSelector } from "../../components/language-selector";
import type { Metadata } from "next";
import { readValidation } from "../../lib/validation";
import { requireUser } from "../../lib/server-auth";
import styles from "./validation.module.css";

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const t = await serverT();
  return { title: `${t("Résultats WF01")} · Emulytix`, description: t("Captures et résultats enregistrés du parcours Chrome, Wikipédia et football.") };
}

function Captures({ run, t }: { run: number; t: Translate }) {
  return (
    <div className={styles.captures}>
      {[
        { file: "query-entered", title: t("1. Recherche saisie"), alt: t("Le mot football saisi dans le champ de recherche de Wikipédia sur Android") },
        { file: "result", title: t("2. Article ouvert"), alt: t("L’article Football de Wikipédia affiché dans Chrome sur Android") }
      ].map((capture) => (
        <figure key={capture.file}>
          <figcaption><strong>{capture.title}</strong><span>{t("Exécution")} {run} {t("· capture enregistrée")}</span></figcaption>
          <a href={`/api/validation/run-${run}-${capture.file}.png`} aria-label={t("Agrandir : {title}, exécution {run}", { title: capture.title, run })}>
            <img src={`/api/validation/run-${run}-${capture.file}.png`} alt={capture.alt} width={320} height={640} />
          </a>
        </figure>
      ))}
    </div>
  );
}

export default async function ValidationPage() {
  await requireUser();
  const [t, locale] = await Promise.all([serverT(), resolveLocale()]);
  const report = await readValidation();
  const succeeded = report?.runs.filter((run) => run.status === "succeeded").length ?? 0;

  return (
    <main className={styles.page}>
      <nav className={styles.navigation} aria-label={t("Navigation Emulytix")}>
        <a href="/">{t("← Tableau de bord")}</a>
        <span>{t("WF01 / Résultats")}</span>
      <LanguageSelector /></nav>

      <header className={styles.header}>
        <span className={styles.eyebrow}>{t("Emulytix · Premier parcours Android")}</span>
        <h1>{t("Chrome → Wikipédia → football")}</h1>
        <p>{t("Le worker ouvre Wikipédia, saisit « football » et vérifie l’article obtenu.")}</p>
      </header>

      {!report ? (
        <section className={styles.panel} aria-labelledby="empty-title">
          <h2 id="empty-title">{t("Preuves indisponibles")}</h2>
          <p>{t("Les résultats enregistrés ne sont pas accessibles dans cette instance. Aucune exécution en direct n’est affichée.")}</p>
        </section>
      ) : (
        <>
          <div className={styles.notice}>
            <strong>{t("Archive du {date} · validation {status}", { date: new Intl.DateTimeFormat(localeInfo[locale].intl, { dateStyle: "long", timeZone: "Europe/Paris" }).format(new Date(report.started_at)), status: report.status === "passed" ? t("réussie") : report.status })}</strong>
            <span>{report.bench_stopped ? t("Émulateur arrêté après validation.") : t("État actuel de l’émulateur non vérifié.")} {t("Ces captures montrent les exécutions enregistrées.")}</span>
          </div>

          <dl className={styles.metrics}>
            <div><dt>{t("Exécutions réussies")}</dt><dd>{succeeded} / {report.runs.length}</dd></div>
            <div><dt>{t("Contrôles de validation")}</dt><dd>{report.checks_passed} / {report.checks_total}</dd></div>
            <div><dt>{t("Appels LLM pendant le parcours")}</dt><dd>{report.llm_calls ?? t("Non mesuré")}</dd></div>
          </dl>

          <div className={styles.content}>
            <section className={styles.panel} aria-labelledby="evidence-title">
              <h2 id="evidence-title">{t("Le résultat sur l’émulateur")}</h2>
              <p>{t("Captures réelles du banc Android. Ouvre une image pour l’agrandir.")}</p>
              {report.runs.length > 0 && <Captures run={1} t={t} />}
              {report.runs.length > 1 && (
                <details className={styles.details}>
                  <summary>{t("Voir les captures de la deuxième exécution")}</summary>
                  <Captures run={2} t={t} />
                </details>
              )}
            </section>

            <aside className={styles.sidebar}>
              <section className={styles.panel} aria-labelledby="delivered-title">
                <h2 id="delivered-title">{t("Ce qui fonctionne")}</h2>
                <ul>
                  <li>{t("Création et stockage des runs dans PostgreSQL.")}</li>
                  <li>{t("Exécution des étapes par le worker Android.")}</li>
                  <li>{t("Vérification de l’URL et du titre « Football ».")}</li>
                  <li>{t("Journal des actions, captures et événements.")}</li>
                  <li>{t("Baux exclusifs, annulation et watchdog.")}</li>
                </ul>
              </section>
              <section className={styles.panel} aria-labelledby="scope-title">
                <h2 id="scope-title">{t("Périmètre du banc")}</h2>
                <p>{t("Android 10 avec Chrome préinstallé. L’installation d’un APK neuf et Android 14 restent à valider.")}</p>
                <p>{t("L’intégration Artemis reste à réaliser.")}</p>
                <a className={styles.reportLink} href="/api/validation/report.json" download="emulytix-wf01-validation.json">{t("Télécharger le rapport JSON ↓")}</a>
              </section>
            </aside>
          </div>

          <section className={styles.panel} aria-labelledby="runs-title">
            <h2 id="runs-title">{t("Les exécutions enregistrées")}</h2>
            <div className={styles.tableWrap} role="region" aria-label={t("Détail des exécutions, défilement horizontal possible")} tabIndex={0}>
              <table className={styles.table}>
                <caption>{t("Résultats du worker sur le banc de validation")}</caption>
                <thead><tr><th scope="col">{t("Exécution")}</th><th scope="col">{t("État")}</th><th scope="col">{t("Étapes")}</th><th scope="col">{t("Actions")}</th><th scope="col">{t("Événements")}</th><th scope="col">{t("Epoch du bail")}</th></tr></thead>
                <tbody>
                  {report.runs.map((run, index) => (
                    <tr key={run.run_id}>
                      <th scope="row"><strong>{t("Exécution")} {index + 1}</strong><code>{run.run_id}</code></th>
                      <td>{run.status === "succeeded" ? t("Réussie") : run.status}</td>
                      <td>{run.step_count}</td><td>{run.action_count}</td><td>{run.event_count}</td><td>{run.lease_epoch}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
