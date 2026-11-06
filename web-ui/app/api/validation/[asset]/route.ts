import { readValidation, readValidationImage } from "../../../../lib/validation";
import { currentUser } from "../../../../lib/server-auth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(_request: Request, context: { params: Promise<{ asset: string }> }) {
  if (!await currentUser()) return Response.json({ detail: "Connexion requise." }, { status: 401, headers: { "Cache-Control": "no-store" } });
  const { asset } = await context.params;
  const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
  if (asset === "report.json") {
    const report = await readValidation();
    if (report) return Response.json(report, { headers });
  } else {
    const bytes = await readValidationImage(asset);
    if (bytes) return new Response(new Uint8Array(bytes), { headers: { ...headers, "Content-Type": "image/png" } });
  }
  return Response.json({ error: "Preuve indisponible" }, { status: 404, headers });
}
