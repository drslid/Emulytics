import { redirect } from "next/navigation";
import { LoginForm } from "../../components/console/login-form";
import { currentUser } from "../../lib/server-auth";

export const dynamic = "force-dynamic";

export default async function Page() {
  if (await currentUser()) redirect("/");
  return <LoginForm />;
}
