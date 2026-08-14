"use client";

import { useEffect, useState } from "react";

import { ApiError, getSettings } from "@/lib/api";
import type { LLMConfigStatus, ProviderInfo } from "@/types";

export type LLMConfig = {
  provider: LLMConfigStatus["provider"];
  providerName: string;
  model: string;
  isMock: boolean;
  providers: ProviderInfo[];
  loading: boolean;
  error: string | null;
};

const MOCK_LABEL = "Free mock classifier";

function resolveProviderName(
  providerId: string,
  providers: ProviderInfo[],
): string {
  return providers.find((p) => p.id === providerId)?.name ?? providerId;
}

function resolveModel(status: LLMConfigStatus): string {
  if (status.provider === "mock") {
    return MOCK_LABEL;
  }
  if (status.model) {
    return status.model;
  }
  const defaultModel = status.providers.find(
    (p) => p.id === status.provider,
  )?.model;
  return defaultModel ?? "";
}

/**
 * Loads the active LLM provider/model configuration from the gateway.
 *
 * The hook is safe to use in any component because it swallows errors and
 * returns a fallback mock configuration rather than throwing.
 */
export function useLLMConfig(): LLMConfig {
  const [status, setStatus] = useState<LLMConfigStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getSettings()
      .then((res) => {
        if (!cancelled) setStatus(res);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "Failed to load LLM config.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status) {
    return {
      provider: "mock",
      providerName: "Mock",
      model: MOCK_LABEL,
      isMock: true,
      providers: [],
      loading,
      error,
    };
  }

  return {
    provider: status.provider,
    providerName: resolveProviderName(status.provider, status.providers),
    model: resolveModel(status),
    isMock: status.provider === "mock",
    providers: status.providers,
    loading,
    error,
  };
}
