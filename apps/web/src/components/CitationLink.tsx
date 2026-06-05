import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ExternalLink, FileText, Quote } from "lucide-react";

import type { Citation } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  citation: Citation;
  /** Inline (next to claim text) vs block (own row). Inline is the
   *  default — shrinks to a small "↗ Source" tag. */
  variant?: "inline" | "block";
}

interface Resolved {
  label: string;
  href: string | null;
  /** Optional verbatim snippet for the hover tooltip. */
  hint: string | null;
}

// Known UK gov data sources — keyed by Citation.data_field prefix.
// Add to this as new gov_data fields appear in agent outputs.
const GOV_SOURCES: Array<{
  prefix: string;
  label: string;
  href: string;
}> = [
  {
    prefix: "sponsor_register",
    label: "UK Sponsor Register",
    href: "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers",
  },
  {
    prefix: "soc_check",
    label: "Skilled Worker SOC threshold",
    href: "https://www.gov.uk/guidance/immigration-rules/immigration-rules-appendix-skilled-occupations",
  },
  {
    prefix: "going_rate",
    label: "Skilled Worker going rate",
    href: "https://www.gov.uk/guidance/immigration-rules/immigration-rules-appendix-skilled-occupations",
  },
  {
    prefix: "ashe",
    label: "ONS ASHE",
    href: "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/bulletins/annualsurveyofhoursandearnings/2023",
  },
  {
    prefix: "companies_house",
    label: "Companies House",
    href: "https://find-and-update.company-information.service.gov.uk/",
  },
];

function resolve(c: Citation): Resolved {
  switch (c.kind) {
    case "url_snippet":
      return {
        label: "Source",
        href: c.url ?? null,
        hint: c.verbatim_snippet ?? null,
      };
    case "gov_data": {
      const match = GOV_SOURCES.find(
        (s) => c.data_field?.startsWith(s.prefix) ?? false,
      );
      const value = c.data_value ? ` · ${c.data_value}` : "";
      if (match) {
        return { label: `${match.label}${value}`, href: match.href, hint: null };
      }
      return {
        label: `UK gov · ${c.data_field ?? "data"}${value}`,
        href: null,
        hint: null,
      };
    }
    case "career_entry":
      return {
        label: "Your career history",
        href: null,
        hint: c.entry_id ? `entry ${c.entry_id.slice(0, 8)}…` : null,
      };
  }
}

export default function CitationLink({ citation, variant = "inline" }: Props) {
  const { label, href, hint } = resolve(citation);
  const [hovered, setHovered] = useState(false);

  const Icon =
    citation.kind === "url_snippet"
      ? ExternalLink
      : citation.kind === "career_entry"
        ? Quote
        : FileText;

  const base = cn(
    "inline-flex items-center gap-1 text-xs",
    variant === "inline"
      ? "rounded bg-secondary px-1.5 py-0.5 text-secondary-foreground"
      : "rounded-md border bg-secondary/50 px-2 py-1 text-secondary-foreground",
  );

  // Anchor or static span depending on whether we have an href.
  // Wrapped in a relative span so the absolute-positioned tooltip
  // anchors to the chip itself, not the document.
  const chip = href ? (
    <motion.a
      href={href}
      target="_blank"
      rel="noreferrer"
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.97 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      className={cn(base, "hover:bg-accent hover:underline")}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
    >
      <Icon className="h-3 w-3" aria-hidden />
      <span className="truncate max-w-[16rem]">{label}</span>
    </motion.a>
  ) : (
    <span
      className={base}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Icon className="h-3 w-3" aria-hidden />
      <span className="truncate max-w-[16rem]">{label}</span>
    </span>
  );

  return (
    <span className="relative inline-block">
      {chip}
      <AnimatePresence mode="wait">
        {hovered && hint && (
          <motion.div
            role="tooltip"
            initial={{ opacity: 0, y: 4, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.96 }}
            transition={{ duration: 0.15 }}
            className={cn(
              "absolute bottom-full left-0 mb-1.5 z-50",
              "max-w-[20rem] rounded-md border bg-card px-2.5 py-1.5",
              "text-xs text-card-foreground shadow-md",
            )}
          >
            {hint}
          </motion.div>
        )}
      </AnimatePresence>
    </span>
  );
}
