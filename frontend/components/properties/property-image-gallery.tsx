"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { pickColor } from "@/lib/charts";

const AUTO_ADVANCE_MS = 2000;

type PropertyImageGalleryProps = {
  images?: string[] | string | null;
  propertyId: number;
  title: string;
  className?: string;
  /** Smaller hero + thumbs — investor detail modal. */
  variant?: "default" | "compact";
  /** Auto-cycle hero when there are 2+ images (default: true for compact). */
  autoPlay?: boolean;
};

function normalizeImages(images?: string[] | string | null): string[] {
  if (!images) return [];
  if (Array.isArray(images)) return images.filter(Boolean);
  if (typeof images === "string") {
    try {
      const parsed = JSON.parse(images) as unknown;
      if (Array.isArray(parsed)) return parsed.map(String).filter(Boolean);
    } catch {
      return images.trim() ? [images] : [];
    }
  }
  return [];
}

export function PropertyImageGallery({
  images,
  propertyId,
  title,
  className,
  variant = "default",
  autoPlay: autoPlayProp,
}: PropertyImageGalleryProps) {
  const compact = variant === "compact";
  const safeImages = normalizeImages(images);
  const [index, setIndex] = useState(0);
  const thumbRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const pauseUntilRef = useRef(0);
  const current = safeImages[index] ?? null;
  const hasMultiple = safeImages.length > 1;
  const autoPlay = (autoPlayProp ?? compact) && hasMultiple;

  useEffect(() => {
    setIndex(0);
    pauseUntilRef.current = 0;
  }, [propertyId, safeImages.length]);

  useEffect(() => {
    if (!autoPlay) return;

    const timer = window.setInterval(() => {
      if (Date.now() < pauseUntilRef.current) return;
      setIndex((value) => (value + 1) % safeImages.length);
    }, AUTO_ADVANCE_MS);

    return () => window.clearInterval(timer);
  }, [autoPlay, safeImages.length, propertyId]);

  useEffect(() => {
    if (!hasMultiple) return;
    thumbRefs.current[index]?.scrollIntoView({
      behavior: "smooth",
      inline: "center",
      block: "nearest",
    });
  }, [index, hasMultiple]);

  function selectImage(next: number) {
    pauseUntilRef.current = Date.now() + AUTO_ADVANCE_MS;
    setIndex(next);
  }

  return (
    <div className={cn(compact ? "space-y-1.5" : "space-y-2", className)}>
      <div
        className={cn(
          "relative w-full overflow-hidden border border-border bg-muted",
          compact ? "aspect-[5/3] rounded-lg" : "aspect-[16/10] rounded-xl",
        )}
        style={
          current
            ? undefined
            : { background: `linear-gradient(135deg, ${pickColor(propertyId)} 0%, hsl(var(--muted)) 100%)` }
        }
      >
        {current ? (
          <img
            key={`${propertyId}-${index}-${current}`}
            src={current}
            alt={title}
            className="h-full w-full object-cover"
          />
        ) : null}

        {autoPlay ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center gap-1">
            {safeImages.map((_, dotIndex) => (
              <span
                key={dotIndex}
                className={cn(
                  "h-1.5 rounded-full bg-white/80 shadow-sm transition-all",
                  dotIndex === index ? "w-4 bg-white" : "w-1.5 opacity-80",
                )}
              />
            ))}
          </div>
        ) : null}
      </div>

      {hasMultiple ? (
        <div className="flex gap-2 overflow-x-auto pb-0.5 scrollbar-thin">
          {safeImages.map((src, i) => (
            <button
              key={`${src}-${i}`}
              ref={(el) => {
                thumbRefs.current[i] = el;
              }}
              type="button"
              onClick={() => selectImage(i)}
              className={cn(
                "relative shrink-0 overflow-hidden rounded-md border-2 transition-colors",
                compact ? "h-10 w-14" : "h-14 w-20 rounded-lg",
                i === index ? "border-primary" : "border-transparent opacity-70 hover:opacity-100",
              )}
            >
              <img src={src} alt="" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
