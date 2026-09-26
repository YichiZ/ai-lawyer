import { cookies } from "next/headers";
import type { Role } from "./api";

export const ROLE_COOKIE = "demo_role";

// Demo only: the role is a cookie the header toggle sets; the API trusts it via X-Demo-User. No real authentication.
export async function currentRole(): Promise<Role> {
  return (await cookies()).get(ROLE_COOKIE)?.value === "reviewer" ? "reviewer" : "researcher";
}
