import type { CostSummary } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  summary: CostSummary;
}

const formatUsd = (n: number): string => {
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
};

export default function CostBreakdown({ summary }: Props) {
  const entries = Object.entries(summary.by_agent).sort(
    ([, a], [, b]) => b - a,
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cost</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-sm">
          <span className="text-muted-foreground">Total spent on this session: </span>
          <span className="font-semibold tabular-nums">
            {formatUsd(summary.total_usd)}
          </span>
        </p>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No LLM calls logged.</p>
        ) : (
          <ul className="divide-y text-sm">
            {entries.map(([agent, cost]) => (
              <li
                key={agent}
                className="flex items-center justify-between py-1.5"
              >
                <span className="text-muted-foreground">{agent}</span>
                <span className="tabular-nums">{formatUsd(cost)}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
