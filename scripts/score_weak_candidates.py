import argparse
import json
import math
from pathlib import Path

import pandas as pd


DEFAULT_RUN_ID = "20260313T032554_4f9be28c"

STRUCTURAL_REASONS = {
    "unseen_origin_for_prefix",
    "unseen_path_for_prefix_origin",
    "unseen_exact_path",
    "weak_path_history",
    "abnormal_path_length_for_prefix_origin",
}

WEAK_REASONS = {
    "unusually_short_duration_for_prefix",
    "unusually_low_visibility_for_prefix",
    "unusually_low_visibility_for_prefix_origin",
    "sparse_short_lived_event",
}

CONTEXTUAL_REASONS = {
    "single_collector_visibility",
}

STRUCTURAL_REASON_WEIGHTS = {
    "unseen_exact_path": 0.40,
    "unseen_path_for_prefix_origin": 0.30,
    "unseen_origin_for_prefix": 0.20,
    "weak_path_history": 0.22,
    "abnormal_path_length_for_prefix_origin": 0.20,
}

WEAK_REASON_WEIGHTS = {
    "unusually_short_duration_for_prefix": 0.28,
    "unusually_low_visibility_for_prefix": 0.26,
    "unusually_low_visibility_for_prefix_origin": 0.24,
    "sparse_short_lived_event": 0.22,
}

CONTEXTUAL_WEAK_WEIGHTS = {
    "single_collector_visibility": 0.05,
}

SCORE_WEIGHTS = {
    "structural_novelty_score": 0.45,
    "weak_signal_score": 0.20,
    "history_rarity_score": 0.20,
    "path_consistency_score": 0.15,
}

DEFAULT_RISK_BUCKET_THRESHOLDS = {
    "high": 70.0,
    "medium": 45.0,
}

MISSING_DAMPEN_RATIO = 0.92


def str2bool(value: str) -> bool:
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def to_rel_path(path: Path) -> str:
    p = path.resolve()
    work_root = Path("/work")
    if work_root.exists():
        try:
            return p.relative_to(work_root).as_posix()
        except ValueError:
            pass
    try:
        return p.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return p.as_posix()


def infer_run_id(path: Path):
    parts = list(path.resolve().parts)
    for idx, part in enumerate(parts):
        if part == "runs" and idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def parse_reason_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return sorted({str(x).strip() for x in value if str(x).strip()})
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [x.strip() for x in text.split("|")]
    if isinstance(parsed, list):
        return sorted({str(x).strip() for x in parsed if str(x).strip()})
    return []


def safe_num(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def ensure_candidate_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "event_id": "",
        "run_id": "",
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "as_path_len": 0.0,
        "duration_sec": 0.0,
        "record_count": 0.0,
        "collector_set": "",
        "collector_count": 0.0,
        "visibility_count": 0.0,
        "candidate_flag": True,
        "candidate_reasons": "[]",
        "matched_rule_count": 0.0,
        "prefix_total_events": None,
        "po_total_events": None,
        "path_total_events": None,
        "po_unique_paths": None,
        "path_seen_before": None,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    out["event_id"] = out["event_id"].fillna("").astype(str)
    out["run_id"] = out["run_id"].fillna("").astype(str)
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["collector_set"] = out["collector_set"].fillna("").astype(str)
    out["candidate_reasons"] = out["candidate_reasons"].fillna("[]").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")

    numeric_cols = [
        "as_path_len",
        "duration_sec",
        "record_count",
        "collector_count",
        "visibility_count",
        "matched_rule_count",
        "prefix_total_events",
        "po_total_events",
        "path_total_events",
        "po_unique_paths",
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if out["candidate_flag"].dtype != bool:
        out["candidate_flag"] = out["candidate_flag"].fillna(False).astype(bool)
    if out["path_seen_before"].dtype != bool:
        path_seen_raw = out["path_seen_before"]
        if path_seen_raw.isna().all():
            out["path_seen_before"] = out["path_total_events"].fillna(0) > 0
        else:
            out["path_seen_before"] = path_seen_raw.fillna(False).astype(bool)
    return out


def ensure_baseline_prefix(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {"prefix": "", "total_events": 0.0}
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["total_events"] = pd.to_numeric(out["total_events"], errors="coerce").fillna(0.0)
    return out


def ensure_baseline_prefix_origin(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "prefix": "",
        "origin_as": None,
        "total_events": 0.0,
        "unique_paths": 0.0,
        "avg_path_len": 0.0,
        "median_path_len": 0.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    for col in ["total_events", "unique_paths", "avg_path_len", "median_path_len"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out


def ensure_baseline_path(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "total_events": 0.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    out["total_events"] = pd.to_numeric(out["total_events"], errors="coerce").fillna(0.0)
    return out


def rarity_from_count(count: float) -> float:
    c = safe_num(count, 0.0)
    if c <= 0:
        return 1.0
    return 1.0 / (1.0 + math.log10(c + 1.0))


def calc_structural_novelty_score(reasons: list[str]) -> tuple[float, list[str]]:
    base = sum(STRUCTURAL_REASON_WEIGHTS.get(r, 0.0) for r in reasons if r in STRUCTURAL_REASON_WEIGHTS)
    structural_hits = [r for r in reasons if r in STRUCTURAL_REASONS]
    if len(structural_hits) >= 2:
        base += 0.10
    if "unseen_exact_path" in structural_hits and "unseen_path_for_prefix_origin" in structural_hits:
        base += 0.08
    return min(100.0, base * 100.0), sorted(set(structural_hits))


def calc_weak_signal_score(reasons: list[str]) -> tuple[float, list[str], list[str]]:
    weak_hits = [r for r in reasons if r in WEAK_REASONS]
    contextual_hits = [r for r in reasons if r in CONTEXTUAL_REASONS]

    base = sum(WEAK_REASON_WEIGHTS.get(r, 0.0) for r in weak_hits)
    if len(set(weak_hits)) >= 2:
        base += 0.08

    contextual_boost = sum(CONTEXTUAL_WEAK_WEIGHTS.get(r, 0.0) for r in contextual_hits)
    base += min(0.05, contextual_boost)
    return min(100.0, base * 100.0), sorted(set(weak_hits)), sorted(set(contextual_hits))


def calc_history_rarity_score(path_seen_before: bool, prefix_total: float, po_total: float, path_total: float) -> float:
    prefix_rarity = rarity_from_count(prefix_total)
    po_rarity = rarity_from_count(po_total)
    path_rarity = 1.0 if not path_seen_before else rarity_from_count(path_total)
    score = (0.25 * prefix_rarity) + (0.35 * po_rarity) + (0.40 * path_rarity)
    return min(100.0, score * 100.0)


def calc_path_consistency_score(
    as_path_len: float,
    po_avg_path_len: float,
    po_median_path_len: float,
    po_unique_paths: float,
    path_seen_before: bool,
    missing_origin_or_path: bool,
) -> tuple[float, dict]:
    ref_len = po_median_path_len if po_median_path_len > 0 else po_avg_path_len
    if ref_len > 0:
        dev_score = min(1.0, abs(as_path_len - ref_len) / max(1.0, ref_len * 0.5))
    elif as_path_len > 0:
        dev_score = min(1.0, as_path_len / 8.0)
    else:
        dev_score = 0.0

    unseen_score = 1.0 if not path_seen_before else 0.0
    if po_unique_paths <= 0:
        diversity_score = 0.8
    elif po_unique_paths <= 2:
        diversity_score = 1.0
    elif po_unique_paths <= 5:
        diversity_score = 0.6
    else:
        diversity_score = 0.25

    score = (0.60 * dev_score) + (0.25 * unseen_score) + (0.15 * diversity_score)
    if missing_origin_or_path:
        score = max(score, 0.65)

    detail = {
        "deviation_component": round(dev_score, 4),
        "unseen_component": round(unseen_score, 4),
        "diversity_component": round(diversity_score, 4),
        "reference_path_len": round(ref_len, 4),
    }
    return min(100.0, score * 100.0), detail


def derive_bucket_thresholds(scores: pd.Series) -> dict:
    clean = pd.to_numeric(scores, errors="coerce").dropna()
    if clean.empty:
        return dict(DEFAULT_RISK_BUCKET_THRESHOLDS)

    high_q = float(clean.quantile(0.80))
    medium_q = float(clean.quantile(0.40))
    if high_q < medium_q:
        high_q = medium_q
    return {"high": high_q, "medium": medium_q}


def risk_bucket(score: float, thresholds: dict) -> str:
    if score >= thresholds["high"]:
        return "high"
    if score >= thresholds["medium"]:
        return "medium"
    return "low"


def top_contributing_factor(contrib: dict) -> str:
    if not contrib:
        return "none"
    return max(contrib.items(), key=lambda kv: kv[1])[0]


def coalesce_numeric(primary: pd.Series, fallback: pd.Series) -> pd.Series:
    p = pd.to_numeric(primary, errors="coerce")
    f = pd.to_numeric(fallback, errors="coerce")
    return p.where(p.notna(), f)


def score_row(row: pd.Series) -> dict:
    reasons = parse_reason_list(row.get("candidate_reasons", "[]"))
    structural_score, structural_hits = calc_structural_novelty_score(reasons)
    weak_score, weak_hits, contextual_hits = calc_weak_signal_score(reasons)

    origin_missing = pd.isna(row.get("origin_as_num"))
    path_clean = str(row.get("as_path_clean", "") or "").strip()
    path_missing = path_clean == ""
    missing_origin_or_path = bool(origin_missing or path_missing)

    as_path_len = safe_num(row.get("as_path_len"), 0.0)
    path_len_inconsistent = bool((path_missing and as_path_len > 0) or ((not path_missing) and as_path_len <= 0))

    prefix_total = safe_num(row.get("prefix_total_events"), 0.0)
    po_total = safe_num(row.get("po_total_events"), 0.0)
    path_total = safe_num(row.get("path_total_events"), 0.0)
    path_seen_before = bool(row.get("path_seen_before", False))
    po_avg_path_len = safe_num(row.get("po_avg_path_len"), 0.0)
    po_median_path_len = safe_num(row.get("po_median_path_len"), 0.0)
    po_unique_paths = safe_num(row.get("po_unique_paths"), 0.0)

    history_score = calc_history_rarity_score(path_seen_before, prefix_total, po_total, path_total)
    path_score, path_detail = calc_path_consistency_score(
        as_path_len=as_path_len,
        po_avg_path_len=po_avg_path_len,
        po_median_path_len=po_median_path_len,
        po_unique_paths=po_unique_paths,
        path_seen_before=path_seen_before,
        missing_origin_or_path=missing_origin_or_path,
    )

    component_scores = {
        "structural_novelty_score": structural_score,
        "weak_signal_score": weak_score,
        "history_rarity_score": history_score,
        "path_consistency_score": path_score,
    }
    contributions = {k: (component_scores[k] * SCORE_WEIGHTS[k]) for k in component_scores}
    risk_score_val = sum(contributions.values())
    if missing_origin_or_path:
        risk_score_val = risk_score_val * MISSING_DAMPEN_RATIO

    risk_score_val = round(min(100.0, max(0.0, risk_score_val)), 4)
    top_factor = top_contributing_factor(contributions)

    notes = []
    if missing_origin_or_path:
        notes.append("missing_origin_or_path")
    if path_len_inconsistent:
        notes.append("path_length_inconsistent")

    explanation = {
        "structural_reasons": structural_hits,
        "weak_reasons": weak_hits,
        "contextual_reasons": contextual_hits,
        "component_scores": {k: round(v, 4) for k, v in component_scores.items()},
        "weighted_contributions": {k: round(v, 4) for k, v in contributions.items()},
        "path_consistency_detail": path_detail,
        "missing_origin_or_path": missing_origin_or_path,
        "notes": notes,
    }

    return {
        "structural_novelty_score": round(structural_score, 4),
        "weak_signal_score": round(weak_score, 4),
        "history_rarity_score": round(history_score, 4),
        "path_consistency_score": round(path_score, 4),
        "risk_score": risk_score_val,
        "top_contributing_factor": top_factor,
        "missing_origin_or_path": missing_origin_or_path,
        "score_explanation": json.dumps(explanation, ensure_ascii=False),
    }


def print_samples(df: pd.DataFrame, title: str, n: int):
    print(f"{title}:")
    if df.empty:
        print("  <empty>")
        return
    cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "candidate_reasons",
        "risk_score",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "score_explanation",
    ]
    for row in df.head(n)[cols].to_dict("records"):
        print("  - " + json.dumps(row, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Score weak anomaly candidates with explainable sub-scores.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--candidates", default=None, help="Path to candidate_events.parquet.")
    ap.add_argument("--baseline-prefix", default=None, help="Path to baseline_prefix.parquet.")
    ap.add_argument("--baseline-prefix-origin", default=None, help="Path to baseline_prefix_origin.parquet.")
    ap.add_argument("--baseline-path", default=None, help="Path to baseline_path.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output score directory.")
    ap.add_argument("--overwrite", type=str2bool, default=False, help="Overwrite existing outputs.")
    args = ap.parse_args()

    if args.candidates:
        candidates_path = Path(args.candidates)
        run_id = args.run_id or infer_run_id(candidates_path) or DEFAULT_RUN_ID
    else:
        run_id = args.run_id or DEFAULT_RUN_ID
        candidates_path = Path("data") / "runs" / run_id / "candidates" / "candidate_events.parquet"

    if not candidates_path.exists():
        raise SystemExit(f"candidate file not found: {candidates_path}")

    baseline_root = Path("data") / "runs" / run_id / "baseline"
    baseline_prefix_path = Path(args.baseline_prefix) if args.baseline_prefix else baseline_root / "baseline_prefix.parquet"
    baseline_po_path = (
        Path(args.baseline_prefix_origin) if args.baseline_prefix_origin else baseline_root / "baseline_prefix_origin.parquet"
    )
    baseline_path_path = Path(args.baseline_path) if args.baseline_path else baseline_root / "baseline_path.parquet"

    for p in [baseline_prefix_path, baseline_po_path, baseline_path_path]:
        if not p.exists():
            raise SystemExit(f"baseline file not found: {p}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "scores"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_scored = output_dir / "scored_candidates.parquet"
    out_summary = output_dir / "score_summary.json"
    if not args.overwrite:
        exists = [p for p in [out_scored, out_summary] if p.exists()]
        if exists:
            raise SystemExit(
                "Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists)
            )

    cand_raw = pd.read_parquet(candidates_path)
    cand_all = ensure_candidate_columns(cand_raw)
    if "candidate_flag" in cand_all.columns:
        candidates = cand_all[cand_all["candidate_flag"]].copy()
    else:
        candidates = cand_all.copy()

    baseline_prefix = ensure_baseline_prefix(pd.read_parquet(baseline_prefix_path))
    baseline_po = ensure_baseline_prefix_origin(pd.read_parquet(baseline_po_path))
    baseline_path_df = ensure_baseline_path(pd.read_parquet(baseline_path_path))

    scored = candidates.merge(
        baseline_prefix[["prefix", "total_events"]].rename(columns={"total_events": "bl_prefix_total_events"}),
        on="prefix",
        how="left",
    )
    scored = scored.merge(
        baseline_po[["prefix", "origin_as_num", "total_events", "unique_paths", "avg_path_len", "median_path_len"]].rename(
            columns={
                "total_events": "bl_po_total_events",
                "unique_paths": "bl_po_unique_paths",
                "avg_path_len": "po_avg_path_len",
                "median_path_len": "po_median_path_len",
            }
        ),
        on=["prefix", "origin_as_num"],
        how="left",
    )
    scored = scored.merge(
        baseline_path_df[["prefix", "origin_as_num", "as_path_clean", "total_events"]].rename(
            columns={"total_events": "bl_path_total_events"}
        ),
        on=["prefix", "origin_as_num", "as_path_clean"],
        how="left",
    )

    scored["prefix_total_events"] = coalesce_numeric(scored["prefix_total_events"], scored["bl_prefix_total_events"])
    scored["po_total_events"] = coalesce_numeric(scored["po_total_events"], scored["bl_po_total_events"])
    scored["po_unique_paths"] = coalesce_numeric(scored["po_unique_paths"], scored["bl_po_unique_paths"])
    scored["path_total_events"] = coalesce_numeric(scored["path_total_events"], scored["bl_path_total_events"])

    derived_seen = scored["path_total_events"].fillna(0) > 0
    if "path_seen_before" in scored.columns:
        scored["path_seen_before"] = scored["path_seen_before"].fillna(derived_seen).astype(bool)
    else:
        scored["path_seen_before"] = derived_seen.astype(bool)

    scored_eval = scored.apply(score_row, axis=1, result_type="expand")
    scored = pd.concat([scored.reset_index(drop=True), scored_eval.reset_index(drop=True)], axis=1)

    output_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "as_path_len",
        "duration_sec",
        "record_count",
        "collector_set",
        "collector_count",
        "visibility_count",
        "candidate_reasons",
        "matched_rule_count",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "risk_score",
        "top_contributing_factor",
        "missing_origin_or_path",
        "path_seen_before",
        "path_total_events",
        "po_total_events",
        "prefix_total_events",
        "score_explanation",
    ]
    output_df = scored[output_cols].copy()
    bucket_thresholds = derive_bucket_thresholds(output_df["risk_score"])
    output_df["risk_bucket"] = output_df["risk_score"].apply(lambda x: risk_bucket(safe_num(x, 0.0), bucket_thresholds))

    ordered_cols = output_cols[:18] + ["risk_bucket"] + output_cols[18:]
    output_df = output_df[ordered_cols]
    output_df.to_parquet(out_scored, index=False)

    bucket_counts = output_df["risk_bucket"].value_counts().to_dict()
    bucket_counts = {str(k): int(v) for k, v in bucket_counts.items()}
    top_factor_counts = output_df["top_contributing_factor"].value_counts().to_dict()
    top_factor_counts = {str(k): int(v) for k, v in top_factor_counts.items()}
    missing_count = int(output_df["missing_origin_or_path"].fillna(False).sum())

    summary = {
        "run_id": run_id,
        "candidates_path": to_rel_path(candidates_path),
        "baseline_prefix_path": to_rel_path(baseline_prefix_path),
        "baseline_prefix_origin_path": to_rel_path(baseline_po_path),
        "baseline_path_path": to_rel_path(baseline_path_path),
        "output_scored_path": to_rel_path(out_scored),
        "output_summary_path": to_rel_path(out_summary),
        "input_rows": int(len(cand_all)),
        "input_candidate_rows": int(len(candidates)),
        "output_rows": int(len(output_df)),
        "avg_risk_score": float(output_df["risk_score"].mean()) if len(output_df) else 0.0,
        "bucket_counts": bucket_counts,
        "top_contributing_factor_counts": top_factor_counts,
        "missing_origin_or_path_count": missing_count,
        "risk_bucket_thresholds": bucket_thresholds,
        "score_weights": SCORE_WEIGHTS,
        "structural_reasons": sorted(STRUCTURAL_REASONS),
        "weak_reasons": sorted(WEAK_REASONS),
        "contextual_reasons": sorted(CONTEXTUAL_REASONS),
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_candidates_path: {to_rel_path(candidates_path)}")
    print(f"input_rows: {len(cand_all)}")
    print(f"input_candidate_rows: {len(candidates)}")
    print(f"output_scored_rows: {len(output_df)}")
    print(f"avg_risk_score: {summary['avg_risk_score']:.4f}")
    print("bucket_counts:")
    print(json.dumps(bucket_counts, ensure_ascii=False, indent=2))
    print("top_contributing_factor_counts:")
    print(json.dumps(top_factor_counts, ensure_ascii=False, indent=2))
    print(f"missing_origin_or_path_count: {missing_count}")
    print(f"output_scored_path: {to_rel_path(out_scored)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")

    print_samples(output_df[output_df["risk_bucket"] == "high"], "high_risk_samples", 10)
    print_samples(output_df[output_df["risk_bucket"] == "medium"], "medium_risk_samples", 10)
    print_samples(output_df[output_df["risk_bucket"] == "low"], "low_risk_samples", 10)
    print_samples(output_df[output_df["missing_origin_or_path"]], "missing_origin_or_path_samples", 5)


if __name__ == "__main__":
    main()
