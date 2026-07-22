import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatDateTime } from "@/lib/utils";
import type { EvidenceItem, EvidenceSource } from "@/types";

const SOURCE_STYLES: Record<EvidenceSource, string> = {
  pod_log: "border-sky-500/40 bg-sky-500/10 text-sky-400",
  previous_pod_log: "border-indigo-500/40 bg-indigo-500/10 text-indigo-400",
  kubernetes_event: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  pod_status: "border-violet-500/40 bg-violet-500/10 text-violet-400",
};

const SOURCE_LABELS: Record<EvidenceSource, string> = {
  pod_log: "Pod log",
  previous_pod_log: "Previous pod log",
  kubernetes_event: "Kubernetes event",
  pod_status: "Pod status",
};

export function EvidenceCard({ item }: { item: EvidenceItem }) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex flex-row flex-wrap items-center gap-2 space-y-0 px-4">
        <Badge variant="outline" className={SOURCE_STYLES[item.source]}>
          {SOURCE_LABELS[item.source]}
        </Badge>
        <span className="text-muted-foreground font-mono text-xs">
          {item.pod}
        </span>
        {item.timestamp ? (
          <span className="text-muted-foreground ml-auto text-xs">
            {formatDateTime(item.timestamp)}
          </span>
        ) : null}
      </CardHeader>
      <CardContent className="px-4">
        <ScrollArea className="bg-muted/40 h-32 rounded-md border">
          <pre className="p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
            {item.evidence}
          </pre>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
