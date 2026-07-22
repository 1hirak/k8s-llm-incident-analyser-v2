import { Skeleton } from "@/components/ui/skeleton";

export default function ReportLoading() {
  return (
    <div>
      <div className="mb-6 space-y-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-96" />
      </div>
      <Skeleton className="h-40" />
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-36" />
        <Skeleton className="h-36" />
      </div>
      <Skeleton className="mt-4 h-32" />
      <Skeleton className="mt-6 h-9 w-96" />
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    </div>
  );
}
