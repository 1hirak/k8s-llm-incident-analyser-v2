import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function StatCard({
  title,
  value,
  hint,
  icon: Icon,
}: {
  title: string;
  value: string;
  hint?: string;
  icon?: LucideIcon;
}) {
  return (
    <Card className="gap-4 py-5 transition-transform duration-300 ease-expo-out hover:-translate-y-1">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-muted-foreground text-sm font-medium">
          {title}
        </CardTitle>
        {Icon ? (
          <span className="flex size-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-muted-foreground">
            <Icon className="size-4" />
          </span>
        ) : null}
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight tabular-nums">
          {value}
        </div>
        {hint ? (
          <p className="mt-1 text-xs text-white/40">{hint}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
