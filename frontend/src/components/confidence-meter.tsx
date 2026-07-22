import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

export function ConfidenceMeter({
  value,
  showLabel = true,
  className,
}: {
  /** Confidence in the range [0, 1]. */
  value: number;
  showLabel?: boolean;
  className?: string;
}) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100);
  const indicatorClassName =
    pct >= 80 ? "bg-emerald-500" : pct >= 60 ? "bg-amber-500" : "bg-red-500";

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <Progress
        value={pct}
        indicatorClassName={indicatorClassName}
        className="h-2 flex-1"
      />
      {showLabel ? (
        <span className="text-muted-foreground w-10 text-right text-sm font-medium tabular-nums">
          {pct}%
        </span>
      ) : null}
    </div>
  );
}
