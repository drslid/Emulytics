import { proxyPersonalAPI } from '../../../../lib/personal-api-proxy';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

async function handle(request: Request, context: { params: Promise<{ path: string[] }> }) {
  return proxyPersonalAPI(request, (await context.params).path);
}

export { handle as GET, handle as POST };
