import Link from "next/link";
import { Activity, ArrowRight, Clock, FileText, Gauge, ScanSearch, Timer } from "lucide-react";

import { CategoryChart } from "@/components/category-chart";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LatencyChart } from "@/components/latency-chart";
import { PageHeader } from "@/components/page-header";
import { ReportsTable } from "@/components/reports-table";
import { SpotlightCard } from "@/components/spotlight-card";
import { StatCard } from "@/components/stat-card";
import { Button } from "@/components/ui/button";
import {
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getStats, listReports } from "@/lib/api";
import { formatChartTime, formatLatency, formatPercent } from "@/lib/utils";
import type { ReportListResponse, StatsResponse } from "@/types";

export default async function DashboardPage() {
  let stats: StatsResponse;
  let reports: ReportListResponse;
  try {
    [stats, reports] = await Promise.all([
      getStats("7d"),
      listReports({ limit: 6 }),
    ]);
  } catch (error) {
    return (
      <>
        <PageHeader
          title="Dashboard"
          description="Incident analysis overview for the last 7 days"
        />
        <ErrorState
          message={
            error instanceof Error ? error.message : "Failed to load dashboard."
          }
        />
      </>
    );
  }

  const categoryData = Object.entries(stats.category_counts)
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count);
  const latencyData = (stats.latency_series ?? []).map((point) => ({
    label: formatChartTime(point.timestamp ?? ""),
    latency_ms: point.latency_ms ?? 0,
  }));

  if (stats.total_reports === 0) {
    return (
      <>
        <PageHeader
          title="Dashboard"
          description="Incident analysis overview for the last 7 days"
        />
        <EmptyState
          icon={Activity}
          title="No incidents analysed yet"
          description="Apply a fault scenario to the demo cluster, then run an analysis to see reports, charts and pipeline metrics here."
        >
          <div className="flex items-center gap-2">
            <Button asChild>
              <Link href="/analyse">Run an analysis</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/scenarios">Browse scenarios</Link>
            </Button>
          </div>
        </EmptyState>
      </>
    );
  }

  return (
    <>
      <PageHeader
        kicker="Overview · Last 7 days"
        title="Dashboard"
        description="Incident analysis across the demo cluster — pipeline health, failure mix and recent reports."
      >
        <Button asChild>
          <Link href="/analyse">
            <ScanSearch />
            Run analysis
          </Link>
        </Button>
      </PageHeader>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Total reports"
          value={String(stats.total_reports)}
          hint="All time"
          icon={FileText}
        />
        <StatCard
          title="Reports (24h)"
          value={String(stats.reports_24h)}
          hint="Last 24 hours"
          icon={Clock}
        />
        <StatCard
          title="Mean latency"
          value={formatLatency(stats.mean_latency_ms)}
          hint="End-to-end pipeline time"
          icon={Timer}
        />
        <StatCard
          title="Mean confidence"
          value={formatPercent(stats.mean_confidence)}
          hint="Average LLM confidence"
          icon={Gauge}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <SpotlightCard className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Failures by category</CardTitle>
            <CardDescription>
              Distribution of the eight failure categories
            </CardDescription>
          </CardHeader>
          <CardContent>
            {categoryData.length > 0 ? (
              <CategoryChart data={categoryData} />
            ) : (
              <p className="text-muted-foreground py-12 text-center text-sm">
                No category data in this range.
              </p>
            )}
          </CardContent>
        </SpotlightCard>
        <SpotlightCard className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Pipeline latency</CardTitle>
            <CardDescription>
              Wall time per analysis over the selected range
            </CardDescription>
          </CardHeader>
          <CardContent>
            {latencyData.length > 0 ? (
              <LatencyChart data={latencyData} />
            ) : (
              <p className="text-muted-foreground py-12 text-center text-sm">
                No latency data in this range.
              </p>
            )}
          </CardContent>
        </SpotlightCard>
      </div>

      <SpotlightCard className="mt-6">
        <CardHeader>
          <CardTitle>Recent reports</CardTitle>
          <CardDescription>
            Latest incident reports across all namespaces
          </CardDescription>
          <CardAction>
            <Button asChild variant="ghost" size="sm">
              <Link href="/reports">
                View all
                <ArrowRight />
              </Link>
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {reports.items.length > 0 ? (
            <ReportsTable reports={reports.items} />
          ) : (
            <p className="text-muted-foreground py-12 text-center text-sm">
              No reports yet.
            </p>
          )}
        </CardContent>
      </SpotlightCard>
    </>
  );
}
