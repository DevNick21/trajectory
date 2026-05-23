// Mirrors PHASE_1_AGENTS in src/trajectory/orchestrator.py — keep
// the order in sync. The dashboard uses this list to render pending
// agents (○) and infer the "currently running" spinner row from
// "first agent in PHASE_1_AGENTS not yet in completed[]".

export const PHASE_1_AGENTS = [
  // Phase 1A (serial — actual execution order)
  "phase_1_jd_extractor",
  "phase_1_company_scraper_summariser",
  "phase_0_triage",
  // Phase 1C (parallel — ordered by typical completion latency)
  "companies_house",
  "sponsor_register",
  "soc_check",
  "gazette_check",
  "reviews",
  "phase_1_ghost_job_jd_scorer",
  "phase_1_red_flags",
] as const;

export type Phase1AgentName = (typeof PHASE_1_AGENTS)[number];

// Friendly labels for the dashboard. Internal agent IDs are clear to
// engineers; users want short, descriptive lines.
export const PHASE_1_AGENT_LABELS: Record<string, string> = {
  phase_0_triage: "Intent triage",
  phase_1_jd_extractor: "Job description parser",
  phase_1_company_scraper_summariser: "Company researcher",
  companies_house: "Companies House (status, director churn, charges, PSC)",
  sponsor_register: "Sponsor register",
  soc_check: "SOC code & salary threshold",
  gazette_check: "The Gazette insolvency notices",
  reviews: "Reviews aggregator",
  phase_1_ghost_job_jd_scorer: "Ghost-job detector",
  phase_1_red_flags: "Red flags",
};

export const labelFor = (agent: string): string =>
  PHASE_1_AGENT_LABELS[agent] ?? agent;
