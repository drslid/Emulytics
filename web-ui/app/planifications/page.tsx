import { ControlConsole } from "../../components/console/control-console";
import { requireUser } from "../../lib/server-auth";
export default async function Page() { return <ControlConsole user={await requireUser()} view="schedules" />; }
