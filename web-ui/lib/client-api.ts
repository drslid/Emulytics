import { browserT } from "./i18n";
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
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
      422: "Vérifiez les informations saisies.",
      429: "Trop de tentatives. Patientez quelques minutes avant de réessayer.",
      503: "Le service est indisponible. Réessayez dans un instant."
    };
    throw new ApiError(response.status, browserT(response.status === 401 && path.startsWith("auth/") && path !== "auth/login" ? "Code incorrect ou connexion expirée. Réessayez avec le code actuel, ou revenez à la connexion." : messages[response.status] ?? "L’action n’a pas abouti. Réessayez."));
  }
  if (response.status === 204) return null as T;
  return response.json() as Promise<T>;
}
