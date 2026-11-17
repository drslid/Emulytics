import { redirect } from "next/navigation";
import { ControlConsole } from "../../../components/console/control-console";
import { canAuthorRun, runSourceId } from "../../../lib/run-authoring";
import { requireUser } from "../../../lib/server-auth";

export default async function Page({ searchParams }: { searchParams: Promise<{ source?: string | string[] }> }) {
  const user = await requireUser();
  if (!canAuthorRun(user.permissions)) redirect("/activite");
  const { source } = await searchParams;
  const sourceRunId = runSourceId(source);
  if (source !== undefined && !sourceRunId) redirect("/activite");
  return <ControlConsole user={user} view="activity" runEditor={{ sourceRunId }} />;
}
