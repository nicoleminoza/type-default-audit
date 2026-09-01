"""Concentration metrics, per model, pooled, and sliced by brief dimension.

Writes audit/metrics.csv and audit/summary.json.

Four definitional choices are made explicitly here rather than being buried,
because each one changes what the numbers mean.

Population. Concentration is computed twice. Over all recommendations, where a
licensed face like Graphik counts as its own item, which measures how narrow the
models are overall. And over Google Fonts hits only, which measures concentration
inside the catalog. Reporting only the second would delete the roughly one third
of recommendations that fall outside the catalog from the concentration story.

Gini zeros. Computed over observed families it measures inequality among fonts
that were recommended at least once, which is comparable between slices.
Computed over the full eligible catalog, with every unrecommended family entering
as a zero, it measures concentration against what was actually available. The
second is the honest headline and will sit near 0.99 regardless. Both are
reported and labelled.

Coverage denominators. A slice that demands Greek is measured against the 118
catalog families that carry Greek, not against all 1955. Using the full catalog
would report the catalog's scarcity as model narrowness.

Sample size. Every row carries its n and a flag when the group is too small to
interpret. The pilot has 20 briefs, so its dimension slices are far too thin to
read, and the output says so rather than letting the numbers imply otherwise.

Usage:  python src/metrics.py
"""

import csv
import json
from collections import Counter, defaultdict

from config import DATA_DIR, PROJECT_ROOT

AUDIT_DIR = PROJECT_ROOT / "audit"

# Below this many briefs a slice is reported but marked unreliable. Concentration
# statistics on a handful of briefs are dominated by which briefs happened to be
# included rather than by anything about the models.
MIN_BRIEFS_FOR_SLICE = 15

DIMENSIONS = ["domain", "tone", "medium", "script", "specificity"]


def gini(counts):
    """Gini coefficient of a list of counts. 0 is perfectly even, 1 is one winner."""
    values = sorted(counts)
    n = len(values)
    total = sum(values)
    if n == 0 or total == 0:
        return None
    weighted = sum((i + 1) * value for i, value in enumerate(values))
    return round((2 * weighted) / (n * total) - (n + 1) / n, 4)


def hhi(counts):
    """Herfindahl-Hirschman index on shares, expressed 0 to 1.

    Reported on the 0 to 1 scale rather than the 0 to 10000 antitrust
    convention. 1 means every recommendation went to a single item.
    """
    total = sum(counts)
    if not total:
        return None
    return round(sum((c / total) ** 2 for c in counts), 4)


def top_share(counts, n):
    total = sum(counts)
    if not total:
        return None
    return round(sum(sorted(counts, reverse=True)[:n]) / total, 4)


def jaccard(a, b):
    union = a | b
    return len(a & b) / len(union) if union else None


def stability(rows):
    """Mean pairwise Jaccard between the sample sets for the same brief and model.

    1.0 means the three samples returned identical sets. This is the reason the
    runner samples at temperature 1.0: at temperature 0 the samples would be near
    copies and this number would describe API determinism, not the model.
    """
    grouped = defaultdict(lambda: defaultdict(set))
    for row in rows:
        grouped[(row["brief_id"], row["model_key"])][row["sample_index"]].add(
            row["identity"])
    scores = []
    overlaps = []
    for samples in grouped.values():
        sets = list(samples.values())
        if len(sets) < 2:
            continue
        pairs = [jaccard(sets[i], sets[j])
                 for i in range(len(sets)) for j in range(i + 1, len(sets))]
        pairs = [p for p in pairs if p is not None]
        if pairs:
            scores.append(sum(pairs) / len(pairs))
        common = set.intersection(*sets)
        overlaps.append(len(common))
    if not scores:
        return None, None, 0
    return (round(sum(scores) / len(scores), 4),
            round(sum(overlaps) / len(overlaps), 2),
            len(scores))


def compute(rows, eligible_denominator, label):
    """All metrics for one group of resolved recommendations."""
    briefs = {r["brief_id"] for r in rows}
    total = len(rows)

    all_counts = Counter(r["identity"] for r in rows)
    gf_rows = [r for r in rows if r["bucket"] == "google_fonts"]
    gf_counts = Counter(r["family"] for r in gf_rows)

    out_of_catalog = sum(1 for r in rows if r["bucket"] == "known_non_google")
    unresolved = sum(1 for r in rows if r["bucket"] == "unresolved")

    # Gini including every eligible family that was never recommended. This is
    # the measure that answers "how concentrated against what was available".
    zeros = max(0, eligible_denominator - len(gf_counts))
    gini_against_catalog = gini(list(gf_counts.values()) + [0] * zeros)

    mean_jaccard, mean_common, pairs = stability(rows)

    return {
        "group": label,
        "briefs": len(briefs),
        "recommendations": total,
        "unique_families_gf": len(gf_counts),
        "eligible_families": eligible_denominator,
        "catalog_coverage": round(len(gf_counts) / eligible_denominator, 4)
                            if eligible_denominator else None,
        "out_of_catalog_share": round(out_of_catalog / total, 4) if total else None,
        "unresolved_share": round(unresolved / total, 4) if total else None,
        "top5_share_all": top_share(list(all_counts.values()), 5),
        "top10_share_all": top_share(list(all_counts.values()), 10),
        "top25_share_all": top_share(list(all_counts.values()), 25),
        "top5_share_gf": top_share(list(gf_counts.values()), 5),
        "top10_share_gf": top_share(list(gf_counts.values()), 10),
        "top25_share_gf": top_share(list(gf_counts.values()), 25),
        "hhi_all": hhi(list(all_counts.values())),
        "hhi_gf": hhi(list(gf_counts.values())),
        "gini_observed_gf": gini(list(gf_counts.values())),
        "gini_against_catalog": gini_against_catalog,
        "stability_mean_jaccard": mean_jaccard,
        "stability_mean_common_of_5": mean_common,
        "stability_brief_model_pairs": pairs,
        "reliable": "yes" if len(briefs) >= MIN_BRIEFS_FOR_SLICE else "NO, n too small",
    }


def main():
    catalog = json.load(open(DATA_DIR / "catalog.json"))
    briefs_doc = json.load(open(PROJECT_ROOT / "briefs.json"))
    eligibility = briefs_doc["script_eligibility"]
    full_catalog = catalog["provenance"]["family_count"]

    rows = []
    with open(DATA_DIR / "resolved.jsonl") as handle:
        for line in handle:
            row = json.loads(line)
            # Identity is what concentration is measured over. A Google family
            # is itself; a licensed face is its own name; an unresolved string
            # is its own name. Collapsing the last two would understate variety.
            row["identity"] = (row["family"] if row["bucket"] == "google_fonts"
                               else row["original_string"])
            row.update(row["brief_tags"])
            rows.append(row)

    results = []
    results.append(compute(rows, full_catalog, "POOLED, all models"))
    for model in sorted({r["model_key"] for r in rows}):
        subset = [r for r in rows if r["model_key"] == model]
        results.append(compute(subset, full_catalog, f"model: {model}"))

    # A cross-model comparison is only valid on briefs every model completed.
    # When a run is partial, each model reaches a different subset, and
    # comparing them measures which briefs each happened to get as much as it
    # measures the models. The study's methodology requires the brief set be
    # held identical across conditions, so the comparison is recomputed here on
    # the intersection, and that intersection is reported alongside it.
    by_model_briefs = {}
    for model in sorted({r["model_key"] for r in rows}):
        by_model_briefs[model] = {r["brief_id"] for r in rows
                                  if r["model_key"] == model}
    common = set.intersection(*by_model_briefs.values()) if by_model_briefs else set()
    comparable = [r for r in rows if r["brief_id"] in common]
    if comparable and len(common) < max(len(v) for v in by_model_briefs.values()):
        results.append(compute(comparable, full_catalog,
                               f"COMMON SUBSET, all models, {len(common)} shared briefs"))
        for model in sorted(by_model_briefs):
            subset = [r for r in comparable if r["model_key"] == model]
            results.append(compute(subset, full_catalog,
                                   f"common subset | model: {model}"))

    for dimension in DIMENSIONS:
        for value in sorted({r[dimension] for r in rows}):
            subset = [r for r in rows if r[dimension] == value]
            denominator = (eligibility.get(value, full_catalog)
                           if dimension == "script" else full_catalog)
            results.append(compute(subset, denominator, f"{dimension}={value}"))
            for model in sorted({r["model_key"] for r in subset}):
                inner = [r for r in subset if r["model_key"] == model]
                results.append(compute(inner, denominator,
                                       f"{dimension}={value} | {model}"))

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = AUDIT_DIR / "metrics.csv"
    with open(metrics_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    # Sensitivity: what happens if every human-reviewed judgment call is reversed.
    strict = [r for r in rows if not r["needs_review"]]
    sensitivity = compute(strict, full_catalog, "POOLED, judgment calls reversed")

    summary = {
        "provenance": {
            "catalog_family_count": full_catalog,
            "catalog_fetched_on": catalog["provenance"]["fetched_on"],
            "briefs_in_run": len({r["brief_id"] for r in rows}),
            "briefs_available": len(briefs_doc["briefs"]),
            "models": sorted({r["model_key"] for r in rows}),
            "recommendations": len(rows),
            "IS_PILOT": len({r["brief_id"] for r in rows}) < len(briefs_doc["briefs"]),
        },
        "pooled": results[0],
        "per_model": [r for r in results if r["group"].startswith("model:")],
        "brief_coverage_per_model": {
            m: len({r["brief_id"] for r in rows if r["model_key"] == m})
            for m in sorted({r["model_key"] for r in rows})},
        "comparable_subset": [r for r in results
                              if r["group"].startswith("common subset")
                              or r["group"].startswith("COMMON SUBSET")],
        "sensitivity_judgment_calls_reversed": sensitivity,
        "pooling_scenarios": briefs_doc["provenance"]["pooling_scenarios"],
        "caveats": briefs_doc["provenance"]["confounds"] + [
            "Concentration is reported over two populations. hhi_all and "
            "top*_share_all treat a licensed face as its own item. hhi_gf and "
            "top*_share_gf cover only recommendations that resolved to the "
            "catalog. Quoting one without saying which is misleading.",
            "gini_against_catalog counts every eligible family that was never "
            "recommended as a zero and will sit near 0.99 in any condition. "
            "gini_observed_gf is the figure that varies between slices.",
            "Rows marked reliable=NO have too few briefs to interpret. In a "
            "pilot that is most of them.",
            "When models cover different numbers of briefs, the per_model rows "
            "are NOT comparable with each other, because each rests on a "
            "different brief set. Use comparable_subset for any cross-model "
            "claim. per_model remains valid as a within-model description.",
        ],
    }
    (AUDIT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))

    pooled = results[0]
    print(f"briefs in run: {summary['provenance']['briefs_in_run']} of "
          f"{summary['provenance']['briefs_available']}"
          + ("   <-- PILOT, slices are not interpretable"
             if summary["provenance"]["IS_PILOT"] else ""))
    print(f"recommendations: {pooled['recommendations']}\n")
    print("POOLED")
    for key in ("unique_families_gf", "catalog_coverage", "out_of_catalog_share",
                "top5_share_all", "top10_share_all", "top25_share_all",
                "hhi_all", "hhi_gf", "gini_observed_gf", "gini_against_catalog",
                "stability_mean_jaccard", "stability_mean_common_of_5"):
        print(f"  {key:<30} {pooled[key]}")
    coverage = summary["brief_coverage_per_model"]
    if len(set(coverage.values())) > 1:
        print("WARNING: models cover different brief counts "
              + ", ".join(f"{m}={n}" for m, n in coverage.items()))
        print("         per-model rows below are NOT comparable with each other.")
        print("         Use the common-subset rows for any cross-model claim.\n")
    print("\nPER MODEL")
    header = f"  {'model':<12}{'uniq':>6}{'cover':>8}{'out':>8}{'top5':>8}{'hhi':>8}{'stab':>8}"
    print(header)
    for row in summary["per_model"]:
        print(f"  {row['group'].replace('model: ',''):<12}"
              f"{row['unique_families_gf']:>6}{row['catalog_coverage']:>8.3f}"
              f"{row['out_of_catalog_share']:>8.3f}{row['top5_share_all']:>8.3f}"
              f"{row['hhi_all']:>8.4f}{row['stability_mean_jaccard']:>8.3f}")
    if summary["comparable_subset"]:
        print("\nCOMMON SUBSET, the only valid cross-model comparison")
        print(f"  {'model':<12}{'uniq':>6}{'cover':>8}{'out':>8}{'top5':>8}{'hhi':>8}{'stab':>8}")
        for row in summary["comparable_subset"]:
            if not row["group"].startswith("common subset"):
                continue
            print(f"  {row['group'].split(': ')[-1]:<12}"
                  f"{row['unique_families_gf']:>6}{row['catalog_coverage']:>8.3f}"
                  f"{row['out_of_catalog_share']:>8.3f}{row['top5_share_all']:>8.3f}"
                  f"{row['hhi_all']:>8.4f}{row['stability_mean_jaccard']:>8.3f}")

    print(f"\nwrote {metrics_path}")
    print(f"wrote {AUDIT_DIR / 'summary.json'}   ({len(results)} metric rows)")


if __name__ == "__main__":
    main()
