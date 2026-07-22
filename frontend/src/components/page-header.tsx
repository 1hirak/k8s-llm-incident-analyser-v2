import type { ReactNode } from "react";

export function PageHeader({
  kicker,
  title,
  description,
  children,
}: {
  kicker?: string;
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="space-y-2">
        {kicker ? (
          <p className="text-accent-indigo font-mono text-[11px] tracking-[0.2em] uppercase">
            {kicker}
          </p>
        ) : null}
        <h1 className="text-gradient text-3xl font-semibold tracking-tight md:text-4xl">
          {title}
        </h1>
        {description ? (
          <p className="text-muted-foreground max-w-prose text-sm md:text-base">
            {description}
          </p>
        ) : null}
      </div>
      {children ? <div className="flex items-center gap-2">{children}</div> : null}
    </div>
  );
}
