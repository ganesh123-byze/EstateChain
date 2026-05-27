"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { refreshMe } from "@/lib/auth";
import { getSession } from "@/lib/api";
import type { Role } from "@/lib/types";

export function RoleGate({ role, children }: { role: Role; children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const session = getSession();
      if (!session) {
        router.replace("/");
        return;
      }
      let me: Awaited<ReturnType<typeof refreshMe>> = null;
      try {
        me = await Promise.race([
          refreshMe(),
          new Promise<null>((_, reject) =>
            window.setTimeout(() => reject(new Error("Auth check timed out")), 20_000),
          ),
        ]);
      } catch {
        if (!cancelled) router.replace("/");
        return;
      }
      if (cancelled) return;
      if (!me) {
        router.replace("/");
        return;
      }
      const r = (me.role || "").toLowerCase();
      if (r !== role) {
        router.replace(`/${r}`);
        return;
      }
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [role, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Authorizing…
      </div>
    );
  }
  return <>{children}</>;
}
