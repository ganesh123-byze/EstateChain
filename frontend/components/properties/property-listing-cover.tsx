"use client";

import { pickColor } from "@/lib/charts";
import { cn } from "@/lib/utils";

/**
 * Single cover image for property listing cards (investor, property owner / admin, tenant).
 * Multi-image galleries belong on the property detail dialog only.
 */
export function PropertyListingCover({
  images,
  propertyId,
  title,
  className,
}: {
  images?: string[];
  propertyId: number;
  title: string;
  className?: string;
}) {
  const cover = (images ?? []).find(Boolean) ?? null;

  return (
    <div
      className={cn("relative overflow-hidden bg-muted", className)}
      style={
        cover
          ? undefined
          : {
              background: `linear-gradient(135deg, ${pickColor(propertyId)} 0%, hsl(var(--muted)) 100%)`,
            }
      }
    >
      {cover ? (
        <img
          src={cover}
          alt={title}
          className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
        />
      ) : null}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/25 to-transparent" />
    </div>
  );
}
