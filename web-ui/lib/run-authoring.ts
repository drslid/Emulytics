import type { Recipe, Step } from "./console-types";

export const runEditorPath = "/activite/nouveau";

export function canAuthorRun(permissions: readonly string[] = []) {
  return ["runs.execute", "workflows.write", "workflows.publish"].every(permission => permissions.includes(permission));
}

export function runSourceId(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value) ? value : undefined;
}

type RecipeBody = { name: string; instructions: string; steps: Step[]; recovery_budget: number };
export type RunRecipeState = {
  initial?: { key: string; body: RecipeBody };
  saved?: Recipe;
  snapshot?: string;
  pendingUpdate?: { body: RecipeBody; revision: number };
};

function rejected(error: unknown) {
  const status = (error as { status?: number } | null)?.status;
  return typeof status === "number" && status >= 400 && status < 500 && status !== 408 && status !== 429;
}

export async function saveRunRecipe(
  body: RecipeBody, state: RunRecipeState,
  request: (path: string, payload: unknown, method?: "POST" | "PATCH") => Promise<Recipe>,
): Promise<Recipe> {
  if (!state.saved) {
    state.initial ??= { key: crypto.randomUUID(), body };
    try {
      state.saved = await request("console/recipes", { ...state.initial.body, request_id: state.initial.key });
      state.snapshot = JSON.stringify(state.initial.body);
    } catch (error) {
      if (rejected(error)) state.initial = undefined;
      throw error;
    }
  }
  // Resolve an uncertain update before applying any newer edits.
  while (state.pendingUpdate || state.snapshot !== JSON.stringify(body)) {
    const pending = state.pendingUpdate ??= { body, revision: state.saved.revision };
    try {
      state.saved = await request(`console/recipes/${state.saved.id}`, { ...pending.body, revision: pending.revision, accept_replay: true }, "PATCH");
      state.snapshot = JSON.stringify(pending.body);
      state.pendingUpdate = undefined;
    } catch (error) {
      if (rejected(error)) state.pendingUpdate = undefined;
      throw error;
    }
  }
  return state.saved;
}
