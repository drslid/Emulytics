import type { Metadata } from "next";
import { readValidation } from "../../lib/validation";
import { requireUser } from "../../lib/server-auth";
import styles from "./validation.module.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Résultats WF01 · Emulytix",
  description: "Captures et résultats enregistrés du parcours Chrome, Wikipédia et football."
};

function Captures({ run }: { run: number }) {
  return (
    <div className={styles.captures}>
      {[
        { file: "query-entered", title: "1. Recherche saisie", alt: "Le mot football saisi dans le champ de recherche de Wikipédia sur Android" },
        { file: "result", title: "2. Article ouvert", alt: "L’article Football de Wikipédia affiché dans Chrome sur Android" }
      ].map((capture) => (
        <figure key={capture.file}>
          <figcaption><strong>{capture.title}</strong><span>Exécution {run} · capture enregistrée</span></figcaption>
          <a href={`/api/validation/run-${run}-${capture.file}.png`} aria-label={`Agrandir : ${capture.title}, exécution ${run}`}>
            <img src={`/api/validation/run-${run}-${capture.file}.png`} alt={capture.alt} width={320} height={640} />
          </a>
        </figure>
      ))}
    </div>
  );
}

export default async function ValidationPage() {
  await requireUser();
  const report = await readValidation();
  const succeeded = report?.runs.filter((run) => run.status === "succeeded").length ?? 0;

  return (
    <main className={styles.page} lang="fr">
      <nav className={styles.navigation} aria-label="Navigation Emulytix">
        <a href="/">← Tour de contrôle</a>
        <span>WF01 / Résultats</span>
      </nav>

      <header className={styles.header}>
        <span className={styles.eyebrow}>Emulytix · Premier parcours Android</span>
        <h1>Chrome → Wikipédia → football</h1>
        <p>Le worker ouvre Wikipédia, saisit « football » et vérifie l’article obtenu.</p>
      </header>

      {!report ? (
        <section className={styles.panel} aria-labelledby="empty-title">
          <h2 id="empty-title">Preuves indisponibles</h2>
          <p>Les résultats enregistrés ne sont pas accessibles dans cette instance. Aucune exécution en direct n’est affichée.</p>
        </section>
      ) : (
        <>
          <div className={styles.notice}>
            <strong>Archive du {new Intl.DateTimeFormat("fr-FR", { dateStyle: "long", timeZone: "Europe/Paris" }).format(new Date(report.started_at))} · validation {report.status === "passed" ? "réussie" : report.status}</strong>
            <span>{report.bench_stopped ? "Émulateur arrêté après validation." : "État actuel de l’émulateur non vérifié."} Ces captures montrent les exécutions enregistrées.</span>
          </div>

          <dl className={styles.metrics}>
            <div><dt>Exécutions réussies</dt><dd>{succeeded} / {report.runs.length}</dd></div>
            <div><dt>Contrôles de validation</dt><dd>{report.checks_passed} / {report.checks_total}</dd></div>
            <div><dt>Appels LLM pendant le parcours</dt><dd>{report.llm_calls ?? "Non mesuré"}</dd></div>
          </dl>

          <div className={styles.content}>
            <section className={styles.panel} aria-labelledby="evidence-title">
              <h2 id="evidence-title">Le résultat sur l’émulateur</h2>
              <p>Captures réelles du banc Android. Ouvre une image pour l’agrandir.</p>
              {report.runs.length > 0 && <Captures run={1} />}
              {report.runs.length > 1 && (
                <details className={styles.details}>
                  <summary>Voir les captures de la deuxième exécution</summary>
                  <Captures run={2} />
                </details>
              )}
            </section>

            <aside className={styles.sidebar}>
              <section className={styles.panel} aria-labelledby="delivered-title">
                <h2 id="delivered-title">Ce qui fonctionne</h2>
                <ul>
                  <li>Création et stockage des runs dans PostgreSQL.</li>
                  <li>Exécution des étapes par le worker Android.</li>
                  <li>Vérification de l’URL et du titre « Football ».</li>
                  <li>Journal des actions, captures et événements.</li>
                  <li>Baux exclusifs, annulation et watchdog.</li>
                </ul>
              </section>
              <section className={styles.panel} aria-labelledby="scope-title">
                <h2 id="scope-title">Périmètre du banc</h2>
                <p>Android 10 avec Chrome préinstallé. L’installation d’un APK neuf et Android 14 restent à valider.</p>
                <p>L’intégration Artemis et le lancement depuis l’interface restent à réaliser.</p>
                <a className={styles.reportLink} href="/api/validation/report.json" download="emulytix-wf01-validation.json">Télécharger le rapport JSON ↓</a>
              </section>
            </aside>
          </div>

          <section className={styles.panel} aria-labelledby="runs-title">
            <h2 id="runs-title">Les exécutions enregistrées</h2>
            <div className={styles.tableWrap} role="region" aria-label="Détail des exécutions, défilement horizontal possible" tabIndex={0}>
              <table className={styles.table}>
                <caption>Résultats du worker sur le banc de validation</caption>
                <thead><tr><th scope="col">Exécution</th><th scope="col">État</th><th scope="col">Étapes</th><th scope="col">Actions</th><th scope="col">Événements</th><th scope="col">Epoch du bail</th></tr></thead>
                <tbody>
                  {report.runs.map((run, index) => (
                    <tr key={run.run_id}>
                      <th scope="row"><strong>Exécution {index + 1}</strong><code>{run.run_id}</code></th>
                      <td>{run.status === "succeeded" ? "Réussie" : run.status}</td>
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
