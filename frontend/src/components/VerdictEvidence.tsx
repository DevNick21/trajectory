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
  className,
}: {
  title: string;
  icon: any;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
  className?: string;
}) {
  return (
    <details
      open={defaultOpen}
      className={cn(
        "group rounded-2xl border border-canvas bg-secondary/5 overflow-hidden transition-all duration-300 open:bg-secondary/20 [&_summary::-webkit-details-marker]:hidden relative",
        className
      )}
    >
      <div className="absolute top-0 left-0 w-full h-px bg-gradient-to-r from-transparent via-primary/20 to-transparent opacity-0 group-open:opacity-100 transition-opacity" />
      <summary className="flex cursor-pointer items-center justify-between px-5 py-4 hover:bg-white/5 transition-colors relative z-10">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-background border border-canvas group-open:border-primary/50 group-open:text-primary transition-colors shadow-inner">
            <Icon className="h-4 w-4" />
          </div>
          <div className="flex flex-col">
            <span className="font-serif text-lg tracking-tight leading-none mb-1">{title}</span>
            <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest opacity-0 group-open:opacity-100 transition-opacity">Detailed Analysis Active</span>
          </div>
          {badge && (
            <span className="text-[10px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded uppercase font-bold tracking-tighter border border-primary/20 ml-2">
              {badge}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <div className="hidden sm:flex items-center gap-1 opacity-0 group-open:opacity-100 transition-opacity">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="w-1 h-1 rounded-full bg-primary/40 animate-pulse" style={{ animationDelay: `${i * 200}ms` }} />
            ))}
          </div>
          <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform duration-300 group-open:rotate-90" />
        </div>
      </summary>
      <div className="px-5 pb-5 pt-2 animate-in fade-in slide-in-from-top-2 duration-300 relative z-10">
        <div className="h-px bg-canvas mb-4" />
        <div className="text-sm leading-relaxed">{children}</div>
      </div>
      
      {/* Background forensic pattern */}
      <div className="absolute inset-0 opacity-[0.03] pointer-events-none group-open:opacity-[0.07] transition-opacity" 
           style={{ backgroundImage: 'radial-gradient(circle, currentColor 1px, transparent 1px)', backgroundSize: '16px 16px' }} />
    </details>
  );
}

export default function VerdictEvidence({ bundle, verdict }: Props) {
  if (!bundle) {
    return (
      <Card className="border-dashed border-canvas bg-transparent overflow-hidden relative">
        <div className="absolute inset-0 bg-grid-white/[0.02] bg-[size:20px_20px]" />
        <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-4 relative z-10">
          <div className="relative">
            <Database className="h-12 w-12 text-primary opacity-20 animate-pulse" />
            <div className="absolute inset-0 blur-xl bg-primary/20 rounded-full" />
          </div>
          <div className="space-y-1">
            <p className="text-sm text-foreground font-mono uppercase tracking-[0.3em]">Awaiting Research Ingest</p>
            <p className="text-[10px] text-muted-foreground font-mono italic">Picky is standing by for target URL...</p>
          </div>
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
        <Section title="Analysis Logic" icon={Scale} defaultOpen badge="Primary Reasoning">
          <div className="grid gap-3">
            {reasoning.map((r, i) => (
              <div key={i} className="p-4 rounded-xl bg-background/50 border border-canvas flex gap-4 relative group/item overflow-hidden">
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary/20 group-hover/item:bg-primary/50 transition-colors" />
                <span className="text-primary font-mono font-bold text-lg opacity-40">{String(i+1).padStart(2, '0')}</span>
                <div className="space-y-2 flex-1">
                  <p className="font-bold text-foreground leading-snug tracking-tight underline decoration-primary/10 underline-offset-4">{r.claim}</p>
                  {r.supporting_evidence && (
                    <div className="p-2 rounded bg-secondary/30 border border-canvas/50">
                      <p className="text-[11px] text-muted-foreground italic font-mono flex items-center gap-2">
                        <Search className="h-3 w-3 text-primary/50" />
                        Evidence: {r.supporting_evidence}
                      </p>
                    </div>
                  )}
                  {r.citation && (
                     <div className="flex justify-end">
                        <span className="citation-chip">{r.citation.kind}</span>
                     </div>
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
                sublabel={ghost.probability?.replace('_', ' ')}
                color={ghost.probability === 'LIKELY_GHOST' ? 'destructive' : ghost.probability === 'POSSIBLE_GHOST' ? 'warning' : 'success'}
                className="w-full sm:w-48 bg-background/40"
              />
              <div className="flex-1 space-y-3 w-full">
                <div className="grid grid-cols-2 gap-2 font-mono text-[10px] uppercase text-muted-foreground">
                  <span className="flex items-center gap-2">
                    <div className="w-1 h-1 rounded-full bg-primary" />
                    Confidence: <span className="text-foreground font-bold">{ghost.confidence}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    <div className="w-1 h-1 rounded-full bg-primary" />
                    Age: <span className="text-foreground font-bold">{ghost.age_days ?? 'Unknown'} days</span>
                  </span>
                </div>
                {ghost.signals && ghost.signals.length > 0 && (
                   <div className="space-y-2">
                     {ghost.signals.map((s, i) => (
                       <div key={i} className="text-[11px] p-2.5 rounded-lg bg-background/50 border border-canvas flex gap-3 items-start group/sig">
                         <div className="p-1 rounded bg-secondary text-primary group-hover/sig:bg-primary group-hover/sig:text-primary-foreground transition-colors">
                            <Search className="h-3 w-3" />
                         </div>
                         <div className="space-y-0.5">
                            <span className="text-[9px] font-bold text-primary uppercase tracking-tighter">{s.type}</span>
                            <p className="text-muted-foreground leading-tight">{s.evidence}</p>
                         </div>
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
              <div className="flex justify-between items-start p-4 rounded-2xl bg-background/30 border border-canvas shadow-inner">
                <div>
                  <h4 className="font-bold text-lg font-serif tracking-tight">{ch.company_name_official}</h4>
                  <div className="flex items-center gap-2 mt-1">
                    <div className="w-2 h-2 rounded-full bg-success animate-pulse" />
                    <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">Verified Companies House Entity</p>
                  </div>
                </div>
                <Badge variant={ch.status === 'active' ? 'success' : 'destructive'} className="font-mono text-[10px] px-3 py-1">
                  {ch.status}
                </Badge>
              </div>
              
              <div className="grid grid-cols-2 gap-3">
                <div className={cn("p-4 rounded-xl border flex flex-col gap-1 transition-all", ch.accounts_overdue ? "border-destructive/30 bg-destructive/5 shadow-[inset_0_0_10px_rgba(220,38,38,0.05)]" : "border-canvas bg-background/30 shadow-inner")}>
                  <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-widest">Accounts Status</span>
                  <span className={cn("text-sm font-mono font-bold", ch.accounts_overdue ? "text-destructive" : "text-success")}>
                    {ch.accounts_overdue ? "OVERDUE" : "UP TO DATE"}
                  </span>
                </div>
                <div className={cn("p-4 rounded-xl border flex flex-col gap-1 transition-all", ch.confirmation_statement_overdue ? "border-destructive/30 bg-destructive/5 shadow-[inset_0_0_10px_rgba(220,38,38,0.05)]" : "border-canvas bg-background/30 shadow-inner")}>
                  <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-widest">Conf. Statement</span>
                  <span className={cn("text-sm font-mono font-bold", ch.confirmation_statement_overdue ? "text-destructive" : "text-success")}>
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
          <Section title="Role Specifications" icon={Search}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 p-4 rounded-2xl bg-background/30 border border-canvas shadow-inner relative overflow-hidden">
              <div className="absolute top-0 right-0 p-2 opacity-5">
                <Search className="h-24 w-24 -rotate-12" />
              </div>
              <DataField label="Designation" value={jd.role_title} />
              <DataField label="Seniority" value={jd.seniority_signal} />
              <DataField label="Location" value={`${jd.location} (${jd.remote_policy})`} />
              <DataField label="SOC Class" value={jd.soc_code_guess} />
              <DataField 
                label="Valuation" 
                value={jd.salary_band ? `£${jd.salary_band.min_gbp?.toLocaleString()} - £${jd.salary_band.max_gbp?.toLocaleString()}` : 'Not Stated'} 
                className="sm:col-span-2 p-3 bg-secondary/20 rounded-xl border border-canvas"
              />
              {jd.required_skills && jd.required_skills.length > 0 && (
                <div className="col-span-2 space-y-2">
                  <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-widest flex items-center gap-2">
                    <div className="w-1 h-1 bg-primary" />
                    Tech Stack Core
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {jd.required_skills.slice(0, 12).map(s => (
                      <span key={s} className="px-2.5 py-1 bg-background rounded border border-canvas text-[10px] font-mono hover:border-primary/50 transition-colors shadow-sm">{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Section>
        )}

        {flags.length > 0 && (
          <Section title="Risk Signals" icon={FileWarning} badge={`${flags.length} Detected`}>
            <div className="space-y-3">
              {flags.map((f, i) => (
                <div key={i} className="flex gap-4 p-4 rounded-xl border border-destructive/20 bg-destructive/5 items-start relative group/flag overflow-hidden">
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-destructive/30 group-hover/flag:bg-destructive transition-colors" />
                  <div className="p-2 rounded-lg bg-destructive/10 text-destructive mt-0.5 shadow-inner">
                    <FileWarning className="h-4 w-4" />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold uppercase text-destructive tracking-[0.2em]">{f.type}</span>
                        {f.severity === 'HARD' && <Badge variant="destructive" className="text-[8px] h-4">CRITICAL</Badge>}
                    </div>
                    <p className="text-xs leading-relaxed font-medium">{f.summary}</p>
                    {f.citation && (
                        <div className="pt-2 flex justify-end">
                            <span className="citation-chip opacity-80 scale-90 origin-right">{f.citation.kind}</span>
                        </div>
                    )}
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
                <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-widest flex items-center gap-2">
                    <div className="w-1 h-1 bg-primary" />
                    Sponsor Registry
                </span>
                <div className="p-5 rounded-2xl bg-background/50 border border-canvas space-y-3 shadow-inner relative group/sp">
                  <div className="absolute top-2 right-2 opacity-0 group-hover/sp:opacity-100 transition-opacity">
                     <ShieldCheck className="h-4 w-4 text-primary" />
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xl font-serif tracking-tight">{sp.matched_name || 'Not Listed'}</span>
                    <Badge variant={sp.status === 'NOT_LISTED' ? 'destructive' : 'success'} className="font-mono text-[10px] uppercase tracking-tighter">
                        {sp.status}
                    </Badge>
                  </div>
                  {sp.rating && (
                    <div className="flex items-center justify-between p-2 rounded bg-secondary/30 border border-canvas/50">
                      <span className="text-[10px] font-mono text-muted-foreground uppercase">Registry Rating</span>
                      <span className="text-primary font-bold font-mono text-xs">{sp.rating}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
            {soc && (
              <div className="space-y-3">
                <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-widest flex items-center gap-2">
                    <div className="w-1 h-1 bg-primary" />
                    SOC Compliance
                </span>
                <div className="p-5 rounded-2xl bg-background/50 border border-canvas space-y-3 shadow-inner relative group/soc">
                  <div className="absolute top-2 right-2 opacity-0 group-hover/soc:opacity-100 transition-opacity">
                     <Building2 className="h-4 w-4 text-primary" />
                  </div>
                   <div className="flex justify-between items-start">
                      <div className="space-y-1">
                        <span className="text-xl font-serif leading-none tracking-tight">{soc.soc_title}</span>
                        <p className="text-[10px] font-mono opacity-50 uppercase tracking-[0.2em] mt-1">{soc.soc_code}</p>
                      </div>
                      {soc.below_threshold && <Badge variant="destructive" className="animate-pulse">THRESHOLD ALERT</Badge>}
                   </div>
                   <div className="space-y-2 pt-2 border-t border-canvas/50">
                        {soc.going_rate_gbp && (
                            <div className="flex justify-between items-center">
                            <span className="text-[10px] text-muted-foreground uppercase font-mono tracking-tighter">Market (ASHE P10)</span>
                            <span className="font-mono font-bold text-xs">£{soc.going_rate_gbp.toLocaleString()}</span>
                            </div>
                        )}
                        {soc.offered_salary_gbp && (
                            <div className="flex justify-between items-center">
                            <span className="text-[10px] text-muted-foreground uppercase font-mono tracking-tighter">Target Offer</span>
                            <span className={cn("font-mono font-bold text-xs", soc.below_threshold ? "text-destructive" : "text-success")}>
                                £{soc.offered_salary_gbp.toLocaleString()}
                            </span>
                            </div>
                        )}
                   </div>
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
    <div className={cn("space-y-1.5", className)}>
      <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-[0.2em]">{label}</span>
      <p className="text-xs font-mono break-words bg-secondary/20 p-2 rounded border border-canvas/50 group-hover:border-primary/20 transition-colors shadow-sm">{value ?? 'N/A'}</p>
    </div>
  );
}
