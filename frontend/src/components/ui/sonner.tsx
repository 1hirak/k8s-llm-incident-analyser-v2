"use client";

import type * as React from "react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

// The console is dark-only, so the theme is fixed instead of being
// driven by next-themes.
function Toaster({ ...props }: ToasterProps) {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
}

export { Toaster };
