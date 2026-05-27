"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  /* defaultTheme is dark — align knob before hydration to avoid a light flash */
  const isDark = mounted ? resolvedTheme === "dark" : true;
  const isTall = className?.includes("h-9");
  const knobClass = isTall ? "h-7 w-7" : "h-5 w-5";

  return (
    <button
      type="button"
      role="switch"
      aria-checked={mounted ? isDark : false}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={cn(
        "relative inline-flex shrink-0 items-center rounded-full border border-border bg-muted/60 p-0.5 transition-colors hover:bg-muted",
        isTall ? "h-9 w-[3.25rem]" : "h-7 w-12",
        isDark ? "justify-end" : "justify-start",
        className,
      )}
    >
      <motion.span
        layout
        transition={{ type: "spring", stiffness: 500, damping: 30 }}
        className={cn(
          "relative z-10 grid place-items-center rounded-full bg-background shadow-md ring-1 ring-border",
          knobClass,
        )}
      >
        {!mounted || isDark ? (
          <Sun className="h-3.5 w-3.5 text-amber-500" aria-hidden />
        ) : (
          <Moon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
        )}
      </motion.span>
    </button>
  );
}
