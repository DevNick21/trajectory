// Mirrors PHASE_1_AGENTS in src/trajectory/orchestrator.py — keep
// the order in sync. The dashboard uses this list to render pending
// agents (○) and infer the "currently running" spinner row from
// "first agent in PHASE_1_AGENTS not yet in completed[]".

export const PHASE_1_AGENTS = [
  // Phase 1A (serial)
  "phase_1_jd_extractor",
  "phase_1_company_scraper_summariser",
  "companies_house",
  // Phase 1C (parallel — ordered by typical completion latency)
  "sponsor_register",
  "soc_check",
  "salary_data",
  "reviews",
  "phase_1_ghost_job_jd_scorer",
  "phase_1_red_flags",
] as const;

export type Phase1AgentName = (typeof PHASE_1_AGENTS)[number];

// Friendly labels for the dashboard. Internal agent IDs are clear to
// engineers; users want short, descriptive lines.
export const PHASE_1_AGENT_LABELS: Record<string, string> = {
  phase_1_jd_extractor: "Job description parser",
  phase_1_company_scraper_summariser: "Company researcher",
  companies_house: "Companies House check",
  sponsor_register: "Sponsor register",
  soc_check: "SOC code & salary threshold",
  salary_data: "Salary benchmarks",
  reviews: "Glassdoor reviews",
  phase_1_ghost_job_jd_scorer: "Ghost-job detector",
  phase_1_red_flags: "Red flags",
};

export const labelFor = (agent: string): string =>
  PHASE_1_AGENT_LABELS[agent] ?? agent;
