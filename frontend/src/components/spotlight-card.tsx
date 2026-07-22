"use client";

import { useRef } from "react";
import type { ComponentProps, MouseEvent } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Card with a mouse-tracking spotlight: a soft radial pool of indigo light
 * (320px, 12% opacity) follows the cursor across the surface.
 * The glow is written straight to the DOM via a ref — no re-renders.
 */
export function SpotlightCard({
  className,
  children,
  ...props
}: ComponentProps<typeof Card>) {
  const frameRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);

  function handleMouseMove(event: MouseEvent<HTMLDivElement>) {
    const frame = frameRef.current;
    const glow = glowRef.current;
    if (!frame || !glow) return;
    const rect = frame.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    glow.style.background = `radial-gradient(320px circle at ${x}px ${y}px, rgba(94, 106, 210, 0.12), transparent 70%)`;
  }

  return (
    <div
      ref={frameRef}
      onMouseMove={handleMouseMove}
      className="group relative h-full"
    >
      <div
        ref={glowRef}
        aria-hidden
        className="pointer-events-none absolute inset-0 z-10 rounded-2xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
      />
      <Card className={cn("h-full", className)} {...props}>
        {children}
      </Card>
    </div>
  );
}
