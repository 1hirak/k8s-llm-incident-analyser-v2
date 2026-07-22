import Link from "next/link";

import { ConfidenceMeter } from "@/components/confidence-meter";
import { CategoryBadge, SeverityBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, shortId } from "@/lib/utils";
import type { ReportSummary } from "@/types";

export function ReportsTable({ reports }: { reports: ReportSummary[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Summary</TableHead>
          <TableHead>Category</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead className="w-[160px]">Confidence</TableHead>
          <TableHead>Target</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {reports.map((report) => (
          <TableRow key={report.incident_id}>
            <TableCell className="max-w-[420px]">
              <Link
                href={`/reports/${report.incident_id}`}
                className="block truncate font-medium hover:underline"
              >
                {report.incident_summary}
              </Link>
              <span className="text-muted-foreground font-mono text-xs">
                {shortId(report.incident_id)}
              </span>
            </TableCell>
            <TableCell>
              <CategoryBadge category={report.failure_category} />
            </TableCell>
            <TableCell>
              <SeverityBadge severity={report.severity} />
            </TableCell>
            <TableCell>
              <ConfidenceMeter value={report.confidence} className="gap-2" />
            </TableCell>
            <TableCell className="font-mono text-xs">
              {report.namespace}/{report.pod_name}
            </TableCell>
            <TableCell className="text-muted-foreground text-xs">
              {formatDateTime(report.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
