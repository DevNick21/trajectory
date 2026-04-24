import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Loose typing — research_bundle + verdict pass through as raw dicts.
// Each section reads what it needs and tolerates missing fields.

interface ReasoningPoint {
  claim?: string;
  supporting_evidence?: string;
}

interface BundleData {
  extracted_jd?: {
    role_title?: string;
    location?: string;
    remote_policy?: string;
    seniority_signal?: string;
    soc_code_guess?: string;
    salary_band?: { min_gbp?: number; max_gbp?: number; period?: string } | null;
    required_skills?: string[];
    posted_date?: string | null;
  };
  company_research?: {
    company_name?: string;
    company_domain?: string | null;
    careers_page_url?: string | null;
    not_on_careers_page?: boolean;
    culture_claims?: Array<{ claim?: string; url?: string }>;
  };
  companies_house?: {
    status?: string;
    company_name_official?: string;
    accounts_overdue?: boolean;
    confirmation_statement_overdue?: boolean;
  } | null;
  sponsor_status?: {
    status?: string;
    matched_name?: string | null;
    rating?: string | null;
  } | null;
  soc_check?: {
    soc_code?: string;
    soc_title?: string;
    going_rate_gbp?: number | null;
    offered_salary_gbp?: number | null;
    below_threshold?: boolean;
  } | null;
  ghost_job?: {
    probability?: string;
    confidence?: string;
    age_days?: number | null;
    signals?: Array<{ type?: string; evidence?: string }>;
  };
  red_flags?: { flags?: Array<{ type?: string; summary?: string }> };
  salary_signals?: {
    sources_consulted?: string[];
  };
}

interface VerdictData {
  reasoning?: ReasoningPoint[];
}

interface Props {
  bundle: BundleData | null;
  verdict: VerdictData | null;
}

function Section({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details
      open={defaultOpen}
      className="group rounded-md border bg-card px-4 py-3 [&_summary::-webkit-details-marker]:hidden"
    >
      <summary className="flex cursor-pointer items-center justify-between text-sm font-medium">
        {title}
        <span className="text-xs text-muted-foreground transition-transform group-open:rotate-90">
          ›
        </span>
      </summary>
      <div className="mt-3 space-y-2 text-sm">{children}</div>
    </details>
  );
}

export default function VerdictEvidence({ bundle, verdict }: Props) {
  if (!bundle) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Evidence</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          No research bundle on this session yet.
        </CardContent>
      </Card>
    );
  }

  const jd = bundle.extracted_jd;
  const cr = bundle.company_research;
  const ch = bundle.companies_house;
  const sp = bundle.sponsor_status;
  const soc = bundle.soc_check;
  const ghost = bundle.ghost_job;
  const flags = bundle.red_flags?.flags ?? [];
  const reasoning = verdict?.reasoning ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Evidence</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {reasoning.length > 0 && (
          <Section title="Reasoning" defaultOpen>
            <ul className="list-disc space-y-1 pl-5">
              {reasoning.map((r, i) => (
                <li key={i}>
                  <span className="font-medium">{r.claim}</span>
                  {r.supporting_evidence && (
                    <span className="text-muted-foreground">
                      {" "}
                      — {r.supporting_evidence}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {jd && (
          <Section title="Job description">
            <dl className="grid grid-cols-2 gap-2">
              {jd.role_title && (
                <>
                  <dt className="text-muted-foreground">Role</dt>
                  <dd>{jd.role_title}</dd>
                </>
              )}
              {jd.seniority_signal && (
                <>
                  <dt className="text-muted-foreground">Seniority</dt>
                  <dd>{jd.seniority_signal}</dd>
                </>
              )}
              {jd.location && (
                <>
                  <dt className="text-muted-foreground">Location</dt>
                  <dd>
                    {jd.location}
                    {jd.remote_policy && (
                      <span className="text-muted-foreground">
                        {" "}
                        · {jd.remote_policy}
                      </span>
                    )}
                  </dd>
                </>
              )}
              {jd.soc_code_guess && (
                <>
                  <dt className="text-muted-foreground">SOC code</dt>
                  <dd>{jd.soc_code_guess}</dd>
                </>
              )}
              {jd.salary_band && (
                <>
                  <dt className="text-muted-foreground">Posted band</dt>
                  <dd>
                    £{jd.salary_band.min_gbp?.toLocaleString()}–£
                    {jd.salary_band.max_gbp?.toLocaleString()}{" "}
                    <span className="text-muted-foreground">
                      ({jd.salary_band.period ?? "?"})
                    </span>
                  </dd>
                </>
              )}
              {jd.required_skills && jd.required_skills.length > 0 && (
                <>
                  <dt className="text-muted-foreground">Skills</dt>
                  <dd>{jd.required_skills.slice(0, 8).join(", ")}</dd>
                </>
              )}
            </dl>
          </Section>
        )}

        {cr && (
          <Section title="Company">
            <dl className="grid grid-cols-2 gap-2">
              <dt className="text-muted-foreground">Name</dt>
              <dd>{cr.company_name}</dd>
              {cr.company_domain && (
                <>
                  <dt className="text-muted-foreground">Domain</dt>
                  <dd>{cr.company_domain}</dd>
                </>
              )}
              {cr.careers_page_url && (
                <>
                  <dt className="text-muted-foreground">Careers</dt>
                  <dd>
                    <a
                      href={cr.careers_page_url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline"
                    >
                      Visit
                    </a>
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">On careers page?</dt>
              <dd>{cr.not_on_careers_page === false ? "Yes" : "No"}</dd>
            </dl>
            {cr.culture_claims && cr.culture_claims.length > 0 && (
              <>
                <p className="mt-2 text-xs font-semibold uppercase text-muted-foreground">
                  Culture claims
                </p>
                <ul className="list-disc space-y-1 pl-5">
                  {cr.culture_claims.slice(0, 5).map((c, i) => (
                    <li key={i}>{c.claim}</li>
                  ))}
                </ul>
              </>
            )}
          </Section>
        )}

        {ghost && (
          <Section title="Ghost-job assessment">
            <dl className="grid grid-cols-2 gap-2">
              <dt className="text-muted-foreground">Probability</dt>
              <dd>{ghost.probability}</dd>
              <dt className="text-muted-foreground">Confidence</dt>
              <dd>{ghost.confidence}</dd>
              {ghost.age_days !== null && ghost.age_days !== undefined && (
                <>
                  <dt className="text-muted-foreground">Age (days)</dt>
                  <dd>{ghost.age_days}</dd>
                </>
              )}
            </dl>
            {ghost.signals && ghost.signals.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {ghost.signals.map((s, i) => (
                  <li key={i}>
                    <span className="font-medium">{s.type}</span>
                    {s.evidence && (
                      <span className="text-muted-foreground"> — {s.evidence}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        )}

        {(sp || soc) && (
          <Section title="Visa / sponsor">
            {sp && (
              <p>
                <span className="text-muted-foreground">Sponsor register: </span>
                <span className="font-medium">{sp.status}</span>
                {sp.matched_name && (
                  <span className="text-muted-foreground">
                    {" "}
                    — {sp.matched_name}
                    {sp.rating && ` (${sp.rating})`}
                  </span>
                )}
              </p>
            )}
            {soc && (
              <p>
                <span className="text-muted-foreground">SOC: </span>
                <span className="font-medium">
                  {soc.soc_code} {soc.soc_title}
                </span>
                {soc.going_rate_gbp && (
                  <span className="text-muted-foreground">
                    {" "}
                    · going rate £{soc.going_rate_gbp.toLocaleString()}
                  </span>
                )}
                {soc.below_threshold && (
                  <span className="ml-1 text-destructive">
                    (below threshold)
                  </span>
                )}
              </p>
            )}
          </Section>
        )}

        {ch && (
          <Section title="Companies House">
            <p>
              <span className="font-medium">{ch.company_name_official}</span>
              <span className="text-muted-foreground"> — {ch.status}</span>
            </p>
            {(ch.accounts_overdue || ch.confirmation_statement_overdue) && (
              <p className="text-destructive">
                {ch.accounts_overdue && "Accounts overdue. "}
                {ch.confirmation_statement_overdue &&
                  "Confirmation statement overdue."}
              </p>
            )}
          </Section>
        )}

        {flags.length > 0 && (
          <Section title={`Red flags (${flags.length})`}>
            <ul className="list-disc space-y-1 pl-5">
              {flags.map((f, i) => (
                <li key={i}>
                  <span className="font-medium">{f.type}</span>
                  {f.summary && (
                    <span className="text-muted-foreground"> — {f.summary}</span>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}
      </CardContent>
    </Card>
  );
}
