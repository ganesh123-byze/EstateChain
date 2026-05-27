"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { pickColor } from "@/lib/charts";

type PropertyImageCarouselProps = {
  images?: string[];
  propertyId: number;
  title: string;
  className?: string;
  children?: React.ReactNode;
  /** Clean hero for listing cards — no title overlay, centered dots */
  variant?: "default" | "listing";
};

export function PropertyImageCarousel({
  images,
  propertyId,
  title,
  className,
  children,
  variant = "default",
}: PropertyImageCarouselProps) {
  const isListing = variant === "listing";
  const safeImages = (images ?? []).filter(Boolean);
  // Listing cards show one cover image only; detail dialogs use PropertyImageGallery.
  const displayImages = isListing ? safeImages.slice(0, 1) : safeImages;
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const current = displayImages[index] ?? null;
  const hasMultiple = !isListing && displayImages.length > 1;

  useEffect(() => {
    setIndex(0);
  }, [propertyId, displayImages.length]);

  useEffect(() => {
    if (!hasMultiple || paused) return;
    const timer = window.setInterval(() => {
      setIndex((value) => (value + 1) % displayImages.length);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [hasMultiple, paused, displayImages.length]);

  function go(delta: number) {
    setIndex((value) => (value + delta + displayImages.length) % displayImages.length);
  }

  return (
    <motion.div
      className={cn("relative h-36 overflow-hidden", className)}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      style={
        current
          ? undefined
          : { background: `linear-gradient(135deg, ${pickColor(propertyId)} 0%, hsl(var(--card)) 100%)` }
      }
    >
      {current ? (
        <img
          key={current}
          src={current}
          alt={title}
          className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
        />
      ) : null}
      {!isListing ? (
        <div className="absolute inset-0 bg-gradient-to-t from-card via-card/45 to-transparent" />
      ) : (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/25 to-transparent" />
      )}

      {hasMultiple ? (
        <>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            className={cn(
              "absolute left-2 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full bg-background/80",
              isListing && "opacity-0 transition-opacity group-hover:opacity-100",
            )}
            onClick={(event) => {
              event.stopPropagation();
              go(-1);
            }}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            className={cn(
              "absolute right-2 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full bg-background/80",
              isListing && "opacity-0 transition-opacity group-hover:opacity-100",
            )}
            onClick={(event) => {
              event.stopPropagation();
              go(1);
            }}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
          <div
            className={cn(
              "absolute bottom-3 flex gap-1",
              isListing ? "left-1/2 -translate-x-1/2" : "right-3",
            )}
          >
            {displayImages.map((_, dotIndex) => (
              <span
                key={dotIndex}
                className={cn(
                  "h-1.5 rounded-full bg-white/70 shadow-sm transition-all",
                  dotIndex === index ? "w-4 bg-white" : "w-1.5",
                )}
              />
            ))}
          </div>
        </>
      ) : null}

      {children}
    </motion.div>
  );
}
