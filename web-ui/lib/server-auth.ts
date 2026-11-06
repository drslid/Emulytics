import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { User } from "./console-types";
export type { User } from "./console-types";

export async function currentUser(): Promise<User | null> {
  const session = (await cookies()).get("emulytix_session");
  const base = process.env.EMULYTIX_API_INTERNAL_URL;
  if (!session || !base) return null;
  try {
    const response = await fetch(`${base.replace(/\/$/, "")}/auth/me`, {
      headers: { Cookie: `emulytix_session=${session.value}` },
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5_000)
    });
    if (!response.ok) return null;
    const data = await response.json();
    return typeof data.user?.id === "string" && typeof data.user?.username === "string" ? data.user : null;
  } catch {
    return null;
  }
}

export async function requireUser(): Promise<User> {
  const user = await currentUser();
  if (!user) redirect("/connexion");
  return user;
}
