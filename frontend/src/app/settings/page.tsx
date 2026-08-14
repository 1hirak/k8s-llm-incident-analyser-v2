"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  CircleAlert,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, getSettings, saveSettings } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { LLMConfigStatus, ProviderInfo } from "@/types";

const MODEL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  mock: [{ value: "", label: "Free mock classifier" }],
  openai: [
    { value: "gpt-4o-mini", label: "GPT-4o mini" },
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "gpt-4.1-mini", label: "GPT-4.1 mini" },
    { value: "gpt-4.1", label: "GPT-4.1" },
    { value: "o3-mini", label: "o3 mini" },
  ],
  anthropic: [
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
    { value: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
    { value: "claude-3-5-haiku-20241022", label: "Claude 3.5 Haiku" },
    { value: "claude-3-7-sonnet-20250219", label: "Claude 3.7 Sonnet" },
    { value: "claude-opus-4-1-20250805", label: "Claude Opus 4.1" },
  ],
  deepseek: [
    { value: "deepseek-chat", label: "DeepSeek Chat" },
    { value: "deepseek-reasoner", label: "DeepSeek Reasoner" },
  ],
  openrouter: [
    { value: "openrouter/free", label: "Free (auto-select)" },
    { value: "meta-llama/llama-3.3-8b-instruct:free", label: "Llama 3.3 8B (free)" },
    { value: "google/gemma-3-27b-it:free", label: "Gemma 3 27B (free)" },
    { value: "openai/gpt-4o-mini", label: "OpenAI GPT-4o mini" },
    { value: "openai/gpt-4.1-mini", label: "OpenAI GPT-4.1 mini" },
    { value: "google/gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { value: "google/gemini-2.5-pro", label: "Gemini 2.5 Pro" },
    { value: "anthropic/claude-3.5-haiku", label: "Claude 3.5 Haiku" },
    { value: "anthropic/claude-3.7-sonnet", label: "Claude 3.7 Sonnet" },
    { value: "deepseek/deepseek-chat-v3-0324", label: "DeepSeek V3" },
    { value: "qwen/qwen-2.5-72b-instruct", label: "Qwen 2.5 72B" },
  ],
};

function AvailabilityBadge({ provider }: { provider: ProviderInfo }) {
  if (provider.id === "mock") {
    return (
      <Badge variant="outline" className="border-sky-500/40 bg-sky-500/10 text-sky-400">
        Always available
      </Badge>
    );
  }
  return provider.available ? (
    <Badge variant="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-400">
      <Check />
      Key configured
    </Badge>
  ) : (
    <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-400">
      <KeyRound />
      Key needed
    </Badge>
  );
}

export default function SettingsPage() {
  const [status, setStatus] = useState<LLMConfigStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState("mock");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await getSettings();
      setStatus(res);
      setSelected(res.provider);
      setModel(res.model ?? "");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load settings.",
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedProvider = status?.providers.find((p) => p.id === selected);
  const selectedModels = selectedProvider?.models?.length
    ? selectedProvider.models
    : (MODEL_OPTIONS[selected] ?? []).map(({ value, label }) => ({
        id: value,
        name: label,
      }));

  async function onSave() {
    if (!status) return;
    setSaving(true);
    try {
      const res = await saveSettings({
        provider: selected as LLMConfigStatus["provider"],
        api_key: apiKey.trim() || undefined,
        clear_key: false,
        model: model.trim() ? model.trim() : null,
      });
      setStatus(res);
      setApiKey("");
      toast.success(`Provider set to ${selectedProvider?.name ?? selected}`, {
        description:
          selected === "mock"
            ? "Analyses will use the mock classifier."
            : "Future analyses will use this provider.",
      });
    } catch (err) {
      toast.error("Failed to save settings", {
        description:
          err instanceof ApiError ? err.message : "Unexpected error.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function onClearConfirm() {
    if (!selectedProvider) return;
    setClearing(true);
    try {
      const res = await saveSettings({
        provider: selectedProvider.id,
        clear_key: true,
      });
      setStatus(res);
      toast.success("API key cleared", {
        description: `${selectedProvider.name} will need a new key before use.`,
      });
      setConfirmClear(false);
    } catch (err) {
      toast.error("Failed to clear API key", {
        description:
          err instanceof ApiError ? err.message : "Unexpected error.",
      });
    } finally {
      setClearing(false);
    }
  }

  if (error) {
    return (
      <>
        <PageHeader
          title="Settings"
          description="Configure the LLM provider used for analyses"
        />
        <ErrorState message={error} onRetry={load} />
      </>
    );
  }

  if (!status) {
    return (
      <>
        <PageHeader
          title="Settings"
          description="Configure the LLM provider used for analyses"
        />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
           {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="Configure the LLM provider used for analyses"
      />

      <div className="space-y-6">
        <div className="flex items-start gap-3 rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-3 text-xs leading-5 text-white/60">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent-indigo" />
          <span>
            API keys are stored server-side by the LLM service and are never
            shown again after you save them. The active provider is used for
            every analysis; saved keys override the environment variables set
            in the container.
          </span>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {status.providers.map((provider) => {
            const active = provider.id === status.provider;
            const selectedCard = provider.id === selected;
            return (
              <button
                key={provider.id}
                type="button"
                onClick={() => {
                  setSelected(provider.id);
                  setApiKey("");
                  setModel(provider.id === status.provider ? (status.model ?? "") : "");
                }}
                className={cn(
                  "relative flex flex-col rounded-xl border p-4 text-left transition-all duration-200",
                  selectedCard
                    ? "border-accent-indigo/50 bg-accent-indigo/[0.06] shadow-inset-highlight"
                    : "border-white/[0.08] bg-white/[0.02] hover:border-white/[0.16]",
                )}
              >
                {active ? (
                  <Badge
                    variant="outline"
                    className="absolute -top-2.5 right-3 border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                  >
                    Active
                  </Badge>
                ) : null}
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "flex size-3.5 items-center justify-center rounded-full border",
                      selectedCard
                        ? "border-accent-bright bg-accent-bright/90"
                        : "border-white/20",
                    )}
                  >
                    {selectedCard ? <Check className="size-2.5 text-white" /> : null}
                  </span>
                  <p className="text-sm font-semibold">{provider.name}</p>
                </div>
                <p className="mt-1 font-mono text-[10px] text-white/35">
                  {provider.id}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <AvailabilityBadge provider={provider} />
                </div>
                <p className="mt-3 font-mono text-[11px] text-white/45">
                  model: {provider.model}
                </p>
              </button>
            );
          })}
        </div>

        <Card>
          <CardHeader>
            <CardTitle>
              {selectedProvider?.name ?? selected}
            </CardTitle>
            <CardDescription>
              {selected === "mock"
                ? "The mock provider is a deterministic heuristic classifier — no API key or external call is needed."
                : `Configure ${selectedProvider?.name ?? selected} for future analyses.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {selected !== "mock" ? (
             <div className="space-y-2">
                <label
                  htmlFor="api_key"
                  className="text-muted-foreground text-sm font-medium"
                >
                  API key
                </label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Input
                      id="api_key"
                      type={showKey ? "text" : "password"}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={
                        selectedProvider?.available
                          ? "Leave empty to keep the stored key"
                          : "Paste the API key"
                      }
                      autoComplete="off"
                      disabled={saving}
                    />
                    <button
                      type="button"
                      onClick={() => setShowKey((v) => !v)}
                      className="text-muted-foreground hover:text-foreground absolute top-1/2 right-3 -translate-y-1/2"
                      aria-label={showKey ? "Hide API key" : "Show API key"}
                    >
                      {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                  {selectedProvider?.available ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="border-red-500/40 text-red-400 hover:bg-red-500/10 hover:text-red-400"
                      onClick={() => setConfirmClear(true)}
                      disabled={saving}
                    >
                      <Trash2 />
                      Clear key
                    </Button>
                  ) : null}
                </div>
                <p className="text-muted-foreground text-xs">
                  Saved keys are stored on the server and are never displayed
                  again.
                </p>
              </div>
            ) : (
              <div className="flex items-start gap-2 rounded-lg border border-sky-300/15 bg-sky-400/[0.05] p-3 text-xs leading-5 text-sky-100/70">
                <CircleAlert className="mt-0.5 size-4 shrink-0 text-sky-300" />
                <span>
                  No configuration needed. Analyses run instantly with
                  deterministic heuristics and no external dependency.
                </span>
              </div>
            )}

            <div className="space-y-2">
              <label
                htmlFor="model"
                className="text-muted-foreground text-sm font-medium"
              >
                Model override{" "}
                <span className="text-white/35">(optional)</span>
              </label>
              <Select
                value={model}
                onValueChange={setModel}
                disabled={saving || selected === "mock"}
              >
                <SelectTrigger id="model" className="w-full">
                  <SelectValue
                    placeholder={
                      selected === "mock"
                        ? "Free mock classifier"
                        : `Default: ${selectedProvider?.model ?? ""}`
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {selectedModels.map((option) => (
                    <SelectItem key={option.id || "mock"} value={option.id || "mock"}>
                      {option.name}
                    </SelectItem>
                  ))}
                  {selected !== "mock" && selectedProvider?.model && !MODEL_OPTIONS[selected]?.some((option) => option.value === selectedProvider.model) ? (
                    <SelectItem value={selectedProvider.model}>{selectedProvider.model}</SelectItem>
                  ) : null}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">
                Leave blank to use the provider default.
              </p>
            </div>
          </CardContent>
          <CardFooter className="justify-end gap-2">
            {selected !== status.provider ? (
              <span className="text-muted-foreground mr-auto text-xs">
                Saving will switch the active provider from{" "}
                <span className="font-mono text-white/60">{status.provider}</span>{" "}
                to <span className="font-mono text-white/60">{selected}</span>.
              </span>
            ) : null}
            <Button onClick={onSave} disabled={saving}>
              {saving ? (
                <>
                  <LoaderCircle className="animate-spin" />
                  Saving…
                </>
              ) : (
                <>
                  <Save />
                  Save
                </>
              )}
            </Button>
          </CardFooter>
        </Card>
      </div>

      <Dialog
        open={confirmClear}
        onOpenChange={(open) => {
          if (!open && !clearing) setConfirmClear(false);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear the stored API key?</DialogTitle>
            <DialogDescription>
              Removes the key for {selectedProvider?.name}. You will need to
              re-enter it before this provider can be used again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmClear(false)}
              disabled={clearing}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={onClearConfirm}
              disabled={clearing}
            >
              {clearing ? (
                <>
                  <LoaderCircle className="animate-spin" />
                  Clearing…
                </>
              ) : (
                "Clear key"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
