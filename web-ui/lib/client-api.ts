import { browserT } from "./i18n";
export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) { super(message); }
}

export async function api<T>(path: string, body?: unknown, method?: "GET" | "POST" | "PATCH" | "DELETE"): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/control/${path}`, {
      method: method ?? (body === undefined ? "GET" : "POST"),
      credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Emulytix-Client": "console" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
  } catch {
    throw new ApiError(0, browserT("La connexion a été interrompue. Vérifiez votre réseau puis réessayez."));
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("auth/")) window.location.assign("/connexion");
    const messages: Record<number, string> = {
      401: "Identifiants ou code incorrects. Réessayez.",
      403: "Cette action n’est pas autorisée. Reconnectez-vous puis réessayez.",
      404: "Cet élément n’est plus disponible. Actualisez la page.",
      409: "L’état a changé ou cet identifiant est déjà utilisé. Actualisez avant de réessayer.",
      410: "Cet élément n’est plus disponible. Actualisez la page.",
      422: "Vérifiez les informations saisies.",
      429: "Trop de tentatives. Patientez quelques minutes avant de réessayer.",
      503: "Le service est indisponible. Réessayez dans un instant."
    };
    const payload = await response.json().catch(() => null);
    const lifecycleMessages: Record<string, string> = {
      workflow_version_has_schedules: "Supprimez d’abord les planifications qui utilisent cette version, même celles en pause.",
      workflow_version_in_use: "Cette version est utilisée par une exécution en attente ou en cours. Attendez sa fin avant de la supprimer.",
      workflow_version_deleted: "Cette version a été supprimée. Choisissez une autre version publiée.",
    };
    const known = ["invalid_email", "email_in_use", "username_in_use", "last_admin_required", "self_security_required", "chatgpt_required", "unsupported_goal", ...Object.keys(lifecycleMessages)];
    const code = typeof payload?.detail?.code === "string" && known.includes(payload.detail.code) ? payload.detail.code : undefined;
    throw new ApiError(response.status, browserT(code && Object.hasOwn(lifecycleMessages, code) ? lifecycleMessages[code] : response.status === 401 && path.startsWith("auth/") && path !== "auth/login" ? "Code incorrect ou connexion expirée. Réessayez avec le code actuel, ou revenez à la connexion." : messages[response.status] ?? "L’action n’a pas abouti. Réessayez."), code);
  }
  if (response.status === 204) return null as T;
  return response.json() as Promise<T>;
}
