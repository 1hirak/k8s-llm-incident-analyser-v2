"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  /** Defaults to router.refresh() when rendered inside a server page. */
  onRetry?: () => void;
}) {
  const router = useRouter();
  const retry = onRetry ?? (() => router.refresh());

  useEffect(() => {
    console.error("[ErrorState]", { title, message });
  }, [title, message]);

  return (
    <Alert variant="destructive">
      <TriangleAlert />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="gap-3">
        <span>
          {message ??
            "The request failed. Check that the gateway is reachable and try again."}
        </span>
        <Button variant="outline" size="sm" onClick={retry}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}
