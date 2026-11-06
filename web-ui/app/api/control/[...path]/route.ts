import { proxyControl } from "../../../../lib/control-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  return proxyControl(request, (await context.params).path);
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
