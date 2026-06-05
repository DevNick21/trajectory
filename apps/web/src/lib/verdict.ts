import type { VerdictLabel } from "./types";

const POSITIVE_LABELS: Set<string> = new Set([
  "STRONG_GO",
  "GO",
  "TRY_ANYWAY",
]);
const BLOCKING_LABELS: Set<string> = new Set(["BLOCKED"]);

export function isPositiveVerdict(label: string): boolean {
  return POSITIVE_LABELS.has(label);
}

export function isBlockingVerdict(label: string): boolean {
  return BLOCKING_LABELS.has(label);
}

export type VerdictTone = "success" | "warning" | "secondary" | "destructive";

export function getVerdictTone(label: VerdictLabel): VerdictTone {
  switch (label) {
    case "STRONG_GO":
    case "GO":
      return "success";
    case "TRY_ANYWAY":
      return "warning";
    case "ASK_FIRST":
    case "PASS":
      return "secondary";
    case "BLOCKED":
      return "destructive";
  }
}

export function getVerdictEmoji(label: VerdictLabel): string {
  switch (label) {
    case "STRONG_GO":
      return "✅";
    case "GO":
      return "✅";
    case "TRY_ANYWAY":
      return "👍";
    case "ASK_FIRST":
      return "❓";
    case "PASS":
      return "⏭️";
    case "BLOCKED":
      return "🚫";
  }
}

export function formatVerdictLabel(label: VerdictLabel): string {
  return label.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
