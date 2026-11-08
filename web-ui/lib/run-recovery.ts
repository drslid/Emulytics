export type RetryDraft = {request_id: string; device_ids: string[]};
export function retryKey(userId: string, runId: string) { return `emulytix:retry:${userId}:${runId}`; }
export function parseRetryDraft(value: unknown): RetryDraft | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (Object.keys(item).sort().join(",") !== "device_ids,request_id" || typeof item.request_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(item.request_id) || !Array.isArray(item.device_ids) || !item.device_ids.length || item.device_ids.length > 100 || !item.device_ids.every(id => typeof id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(id)) || new Set(item.device_ids).size !== item.device_ids.length) return null;
  return item as RetryDraft;
}
export function diagnosisMessage(code: string) {
  const copy: Record<string, string> = {
    uncertain_effect: "Le résultat d’une action est incertain. Vérifiez les preuves avant toute nouvelle tentative.",
    application_missing: "Une application manque. Préparez les applications de cet appareil.",
    device_connection: "La connexion Android a été interrompue. Vérifiez l’appareil et son worker.",
    element_not_found: "Un élément attendu est introuvable. Consultez la dernière capture et adaptez le parcours.",
    result_not_verified: "Le résultat attendu n’a pas été confirmé. Comparez les preuves avec l’objectif.",
    timeout: "Le délai est dépassé. Vérifiez la connexion et le chargement de l’application.",
    execution_failed: "Le parcours a échoué. Consultez l’étape concernée et son journal.",
  };
  return Object.hasOwn(copy, code) ? copy[code] : "Consultez les étapes et les captures de cette exécution.";
}
