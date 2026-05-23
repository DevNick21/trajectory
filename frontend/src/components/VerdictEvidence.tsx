import {
  Search,
  Building2,
  Ghost,
  ShieldCheck,
  FileWarning,
  Scale,
  ChevronRight,
  Database,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import Gauge from "@/components/ui/Gauge";
import type { ResearchBundle, VerdictPayload } from "@/lib/types";

interface Props {
  bundle: ResearchBundle | null;
  verdict: VerdictPayload | null;
}

function Section({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
  badge,
}: {
  title: string;
  icon: any;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}) {
  return (
    <details
      open={defaultOpen}
      className="group rounded-2xl border border-canvas bg-secondary/10 overflow-hidden transition-all duration-300 open:bg-secondary/20 [&_summary::-webkit-details-marker]:hidden"
    >
      <summary className="flex cursor-pointer items-center justify-between px-5 py-4 hover:bg-white/5 transition-colors">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-background border border-canvas group-open:border-primary/50 group-open:text-primary transition-colors">
            <Icon className="h-4 w-4" />
          </div>
          <span className="font-serif text-lg tracking-tight">{title}</span>
          {badge && (
            <span className="text-[10px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded uppercase font-bold tracking-tighter">
              {badge}
            </span>
          )}
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform duration-300 group-open:rotate-90" />
      </summary>
      <div className="px-5 pb-5 pt-2 animate-in fade-in slide-in-from-top-2 duration-300">
        <div className="h-px bg-canvas mb-4" />
        <div className="text-sm leading-relaxed">{children}</div>
      </div>
    </details>
  );
}

export default function VerdictEvidence({ bundle, verdict }: Props) {
  if (!bundle) {
    return (
      <Card className="border-dashed border-canvas bg-transparent">
        <CardContent className="flex flex-col items-center justify-center py-12 text-center space-y-3">
          <Database className="h-10 w-10 text-muted-foreground opacity-20" />
          <p className="text-sm text-muted-foreground font-mono uppercase tracking-widest">Awaiting Research Ingest...</p>
        </CardContent>
      </Card>
    );
  }

  const jd = bundle.extracted_jd;
  const ch = bundle.companies_house;
  const sp = bundle.sponsor_status;
  const soc = bundle.soc_check;
  const ghost = bundle.ghost_job;
  const flags = bundle.red_flags?.flags ?? [];
  const reasoning = verdict?.reasoning ?? [];

  return (
    <div className="space-y-4">
      {reasoning.length > 0 && (
        <Section title="Logic Engine Output" icon={Scale} defaultOpen badge="Primary Reasoning">
          <div className="grid gap-3">
            {reasoning.map((r, i) => (
              <div key={i} className="p-3 rounded-xl bg-background/50 border border-canvas flex gap-3">
                <span className="text-primary font-mono font-bold">{String(i+1).padStart(2, '0')}</span>
                <div className="space-y-1">
                  <p className="font-bold text-foreground leading-snug">{r.claim}</p>
                  {r.supporting_evidence && (
                    <p className="text-xs text-muted-foreground italic">Evidence: {r.supporting_evidence}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {ghost && (
          <Section title="Truth/Ghost Scan" icon={Ghost} badge={ghost.probability?.toUpperCase()}>
            <div className="flex flex-col sm:flex-row gap-6 items-center">
              <Gauge 
                value={ghost.probability === 'LIKELY_GHOST' ? 0.85 : ghost.probability === 'POSSIBLE_GHOST' ? 0.45 : 0.1} 
                label="Bullshit Meter"
                color={ghost.probability === 'LIKELY_GHOST' ? 'destructive' : ghost.probability === 'POSSIBLE_GHOST' ? 'warning' : 'success'}
                className="w-full sm:w-48 bg-background/40"
              />
              <div className="flex-1 space-y-3">
                <div className="grid grid-cols-2 gap-2 font-mono text-[10px] uppercase text-muted-foreground">
                  <span>Confidence: <span className="text-foreground">{ghost.confidence}</span></span>
                  <span>Age: <span className="text-foreground">{ghost.age_days ?? 'Unknown'} days</span></span>
                </div>
                {ghost.signals && ghost.signals.length > 0 && (
                   <div className="space-y-2">
                     {ghost.signals.map((s, i) => (
                       <div key={i} className="text-xs p-2 rounded bg-background/50 border border-canvas">
                         <span className="text-primary font-bold">{s.type}:</span> {s.evidence}
                       </div>
                     ))}
                   </div>
                )}
              </div>
            </div>
          </Section>
        )}

        {ch && (
          <Section title="Corporate Forensics" icon={Building2} badge={ch.status?.toUpperCase()}>
            <div className="space-y-4">
              <div className="flex justify-between items-start">
                <div>
                  <h4 className="font-bold text-base">{ch.company_name_official}</h4>
                  <p className="text-xs font-mono text-muted-foreground">Companies House ID: Verified</p>
                </div>
                <Badge variant={ch.status === 'active' ? 'success' : 'destructive'} className="font-mono text-[10px]">
                  {ch.status}
                </Badge>
              </div>
              
              <div className="grid grid-cols-2 gap-3">
                <div className={cn("p-3 rounded-xl border flex flex-col gap-1", ch.accounts_overdue ? "border-destructive/30 bg-destructive/5" : "border-canvas bg-background/30")}>
                  <span className="text-[9px] uppercase font-bold text-muted-foreground">Accounts Status</span>
                  <span className={cn("text-xs font-bold", ch.accounts_overdue ? "text-destructive" : "text-success")}>
                    {ch.accounts_overdue ? "OVERDUE" : "UP TO DATE"}
                  </span>
                </div>
                <div className={cn("p-3 rounded-xl border flex flex-col gap-1", ch.confirmation_statement_overdue ? "border-destructive/30 bg-destructive/5" : "border-canvas bg-background/30")}>
                  <span className="text-[9px] uppercase font-bold text-muted-foreground">Conf. Statement</span>
                  <span className={cn("text-xs font-bold", ch.confirmation_statement_overdue ? "text-destructive" : "text-success")}>
                    {ch.confirmation_statement_overdue ? "OVERDUE" : "UP TO DATE"}
                  </span>
                </div>
              </div>
            </div>
          </Section>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {jd && (
          <Section title="Extracted DNA" icon={Search}>
            <div className="grid grid-cols-2 gap-4">
              <DataField label="Designation" value={jd.role_title} />
              <DataField label="Seniority" value={jd.seniority_signal} />
              <DataField label="Location" value={`${jd.location} (${jd.remote_policy})`} />
              <DataField label="SOC Class" value={jd.soc_code_guess} />
              <DataField 
                label="Valuation" 
                value={jd.salary_band ? `£${jd.salary_band.min_gbp?.toLocaleString()} - £${jd.salary_band.max_gbp?.toLocaleString()}` : 'Not Stated'} 
                className="col-span-2"
              />
              {jd.required_skills && jd.required_skills.length > 0 && (
                <div className="col-span-2 space-y-1">
                  <span className="text-[9px] uppercase font-bold text-muted-foreground">Tech Stack</span>
                  <div className="flex flex-wrap gap-1">
                    {jd.required_skills.slice(0, 10).map(s => (
                      <span key={s} className="px-2 py-0.5 bg-background rounded border border-canvas text-[10px] font-mono">{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Section>
        )}

        {flags.length > 0 && (
          <Section title="Risk Signals" icon={FileWarning} badge={`${flags.length} Detected`}>
            <div className="space-y-2">
              {flags.map((f, i) => (
                <div key={i} className="flex gap-3 p-3 rounded-xl border border-destructive/20 bg-destructive/5 items-start">
                  <div className="p-1 rounded bg-destructive/20 text-destructive mt-0.5">
                    <FileWarning className="h-3 w-3" />
                  </div>
                  <div className="space-y-0.5">
                    <span className="text-[10px] font-bold uppercase text-destructive tracking-widest">{f.type}</span>
                    <p className="text-xs leading-relaxed">{f.summary}</p>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}
      </div>

      {(sp || soc) && (
        <Section title="Sponsorship & Legal" icon={ShieldCheck}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {sp && (
              <div className="space-y-3">
                <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-widest">Sponsor Registry</span>
                <div className="p-4 rounded-2xl bg-background/50 border border-canvas space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-lg font-serif">{sp.matched_name || 'Not Listed'}</span>
                    <Badge variant={sp.status === 'NOT_LISTED' ? 'destructive' : 'success'}>{sp.status}</Badge>
                  </div>
                  {sp.rating && (
                    <div className="flex items-center gap-2 text-xs font-mono">
                      <span className="opacity-50 text-muted-foreground">Rating:</span>
                      <span className="text-primary font-bold">{sp.rating}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
            {soc && (
              <div className="space-y-3">
                <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-widest">SOC Compliance</span>
                <div className="p-4 rounded-2xl bg-background/50 border border-canvas space-y-2">
                   <div className="flex justify-between items-start">
                      <div className="space-y-1">
                        <span className="text-lg font-serif leading-none">{soc.soc_title}</span>
                        <p className="text-[10px] font-mono opacity-50 uppercase tracking-tighter">{soc.soc_code}</p>
                      </div>
                      {soc.below_threshold && <Badge variant="destructive">BELOW THRESHOLD</Badge>}
                   </div>
                   {soc.going_rate_gbp && (
                    <div className="flex justify-between items-center pt-2 border-t border-canvas mt-2">
                      <span className="text-[10px] text-muted-foreground uppercase">Market Rate</span>
                      <span className="font-mono font-bold">£{soc.going_rate_gbp.toLocaleString()}</span>
                    </div>
                   )}
                </div>
              </div>
            )}
          </div>
        </Section>
      )}
    </div>
  );
}

function DataField({ label, value, className }: { label: string; value?: string | null; className?: string }) {
  return (
    <div className={cn("space-y-1", className)}>
      <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-widest">{label}</span>
      <p className="text-xs font-mono truncate">{value ?? 'N/A'}</p>
    </div>
  );
}
