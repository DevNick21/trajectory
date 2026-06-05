"""Train a Splink model for sponsor-register matching.

Outputs `data/processed/sponsor_splink_model.json`. The sponsor matcher
loads this artifact when `enable_splink_sponsor_match=True` and uses it
to rescore candidates in the ambiguous band (default 80-95).

Run:
    python scripts/train_sponsor_splink.py

The trainer mirrors the kanu/DDCE `resolution.splink_resolver._build_settings`
shape:
  - link_only mode (sponsor matcher is 1:N, not dedupe)
  - JaroWinkler bands [0.97, 0.92]
  - Levenshtein bands [3, 7]
  - ExactMatch on first_token as a cheap discriminator
  - block on first_token + substr(name, 1, 4)

EM is trained on a synthetic split of the register: the left side is
the cleaned register, the right side is a perturbed copy (suffixes
stripped, abbreviations swapped). This gives EM a realistic
query/register mismatch distribution to learn m-probabilities from,
without needing a labelled training set.

The artifact format is the dict accepted by Splink's `SettingsCreator`,
NOT the full linker state. The runtime adapter rebuilds the linker
per-query against a 1-row query frame; that pattern is what makes a
single-name lookup tractable.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Allow running as `python scripts/...` without install.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "engine" / "src"))

from askpicky.sub_agents.sponsor_register import (
    _ABBREVIATIONS,
    _LEGAL_SUFFIX_RE,
    _TRADING_AS_RE,
    _normalise,
    _strip_legal_suffix,
)


_OUTPUT_PATH = ROOT / "data" / "processed" / "sponsor_splink_model.json"
_PARQUET_PATH = ROOT / "data" / "processed" / "sponsor_register.parquet"


def _perturb(name: str, rng: random.Random) -> Optional[str]:
    """Generate a realistic perturbation of a register name.

    Models the kinds of differences that bite the matcher in production:
      - legal-suffix dropped (most common careers-page form)
      - trade name only (when register row has "X Ltd t/a Brand")
      - abbreviation swap (intl ↔ international)
    """
    base = _normalise(name)
    if not base:
        return None
    options: list[str] = []

    bare = _strip_legal_suffix(base)
    if bare and bare != base:
        options.append(bare)

    parts = _TRADING_AS_RE.split(base, maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        options.append(parts[1].strip())

    for abbrev, expansion in _ABBREVIATIONS.items():
        if abbrev in base.split():
            options.append(" ".join(base.replace(abbrev, expansion).split()))
        elif expansion in base:
            options.append(" ".join(base.replace(expansion, abbrev).split()))

    if not options:
        return None
    return rng.choice(options)


def _build_pairs(df: pd.DataFrame, name_col: str, max_pairs: int = 50_000) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construct (left, right) frames for link_only EM training.

    Each register row appears on the left side with its normalised name.
    Each row also generates 0-1 perturbed twins on the right side. EM
    learns m-probabilities from the (left_i ↔ right_i) latent matches
    and u-probabilities from the random non-matches in other blocks.
    """
    rng = random.Random(42)
    left_rows: list[dict] = []
    right_rows: list[dict] = []
    raw_names = df[name_col].astype(str).tolist()
    for i, raw in enumerate(raw_names):
        n = _normalise(raw)
        if not n:
            continue
        first_token = n.split(" ", 1)[0]
        left_rows.append({"unique_id": f"l_{i}", "name": n, "first_token": first_token})
        twin = _perturb(raw, rng)
        if twin and twin != n:
            right_rows.append(
                {"unique_id": f"r_{i}", "name": twin, "first_token": twin.split(" ", 1)[0]}
            )
        if len(left_rows) >= max_pairs:
            break

    return pd.DataFrame(left_rows), pd.DataFrame(right_rows)


def main() -> None:
    if not _PARQUET_PATH.exists():
        raise SystemExit(
            f"Sponsor register parquet not found at {_PARQUET_PATH}. "
            "Run `python scripts/fetch_gov_data.py` first."
        )

    print(f"Loading {_PARQUET_PATH} ...")
    df = pd.read_parquet(_PARQUET_PATH)
    lowered = {c.lower(): c for c in df.columns}
    name_col = lowered.get("organisation name") or lowered.get("name")
    if not name_col:
        raise SystemExit("Sponsor parquet missing organisation-name column.")

    print(f"Building synthetic training pairs from {len(df):,} rows ...")
    left, right = _build_pairs(df, name_col)
    print(f"  left={len(left):,}, right={len(right):,}")

    try:
        from splink import DuckDBAPI, Linker, SettingsCreator
        from splink import comparison_library as cl
        from splink.blocking_rule_library import block_on
    except ImportError as exc:
        raise SystemExit(
            "splink not installed. `pip install splink` first."
        ) from exc

    settings = SettingsCreator(
        link_type="link_only",
        blocking_rules_to_generate_predictions=[
            block_on("first_token"),
            block_on("substr(name, 1, 4)"),
        ],
        comparisons=[
            cl.JaroWinklerAtThresholds("name", [0.97, 0.92]),
            cl.LevenshteinAtThresholds("name", [3, 7]),
            cl.ExactMatch("first_token"),
        ],
        retain_intermediate_calculation_columns=False,
        em_convergence=0.001,
        max_iterations=25,
    )

    db_api = DuckDBAPI()
    linker = Linker([left, right], settings, db_api=db_api, input_table_aliases=["l", "r"])

    print("Estimating u probabilities by random sampling ...")
    linker.training.estimate_u_using_random_sampling(max_pairs=2_000_000)

    # Two EM passes with different blocking rules so every comparison
    # gets m-probability estimates. EM cannot estimate the m-probability
    # of a comparison that is also the blocking rule — every blocked
    # pair would trivially satisfy it (tautology). So:
    #   pass 1 blocks on `first_token`        → estimates `name` levels
    #   pass 2 blocks on `substr(name, 1, 4)` → estimates `first_token`
    # Without pass 2, predict() at runtime emits "first_token m values
    # not fully trained" on every call.
    print("EM pass 1: blocking on first_token (trains `name` m-probs) ...")
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("first_token")
    )

    print("EM pass 2: blocking on substr(name, 1, 4) (trains `first_token` m-probs) ...")
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("substr(name, 1, 4)")
    )

    # Persist the trained settings as the dict accepted by SettingsCreator.
    # The Splink Linker API exposes save_model_to_json; we read it back as
    # plain JSON so the runtime adapter can rehydrate via SettingsCreator(**dict).
    tmp_path = _OUTPUT_PATH.with_suffix(".json.tmp")
    linker.misc.save_model_to_json(str(tmp_path), overwrite=True)
    with open(tmp_path) as f:
        model_dict = json.load(f)
    tmp_path.unlink()

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(model_dict, f, indent=2)
    print(f"Saved trained model to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
