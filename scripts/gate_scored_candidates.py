import argparse
import json
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

GATING_CONFIG = {
    "certainty_threshold_high": 65.0,
    "certainty_threshold_medium": 45.0,
    "conflict_threshold_high": 35.0,
    "conflict_threshold_medium": 50.0,
    "promote_low_structural_min": 45.0,
    "promote_low_certainty_min": 45.0,
}


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


def clip_0_100(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "event_id": "",
        "run_id": "",
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "risk_score": 0.0,
        "risk_bucket": "low",
        "structural_novelty_score": 0.0,
        "weak_signal_score": 0.0,
        "history_rarity_score": 0.0,
        "path_consistency_score": 0.0,
        "top_contributing_factor": "",
        "matched_rule_count": 0.0,
        "missing_origin_or_path": False,
        "candidate_reasons": "[]",
        "path_seen_before": False,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    text_cols = ["event_id", "run_id", "prefix", "as_path_clean", "risk_bucket", "top_contributing_factor", "candidate_reasons"]
    for col in text_cols:
        out[col] = out[col].fillna("").astype(str)

    numeric_cols = [
        "risk_score",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "matched_rule_count",
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    if out["missing_origin_or_path"].dtype != bool:
        out["missing_origin_or_path"] = out["missing_origin_or_path"].fillna(False).astype(bool)
    if out["path_seen_before"].dtype != bool:
        out["path_seen_before"] = out["path_seen_before"].fillna(False).astype(bool)
    return out


def calc_certainty_score(row: pd.Series, reasons: list[str]) -> tuple[float, dict]:
    risk = safe_num(row.get("risk_score"))
    structural = safe_num(row.get("structural_novelty_score"))
    weak = safe_num(row.get("weak_signal_score"))
    history = safe_num(row.get("history_rarity_score"))
    path_consistency = safe_num(row.get("path_consistency_score"))
    matched = safe_num(row.get("matched_rule_count"))
    bucket = str(row.get("risk_bucket", "low") or "low")
    top_factor = str(row.get("top_contributing_factor", "") or "")
    missing = bool(row.get("missing_origin_or_path", False))

    structural_hits = [r for r in reasons if r in STRUCTURAL_REASONS]
    weak_hits = [r for r in reasons if r in WEAK_REASONS]

    base = 0.45 * structural
    base += 0.15 * risk
    base += 0.10 * min(100.0, matched * 20.0)

    if top_factor == "structural_novelty_score":
        base += 8.0
    if structural_hits:
        base += 6.0
    if len(structural_hits) >= 2:
        base += 6.0
    if bucket == "high" and structural >= 45.0 and not missing:
        base += 6.0

    if weak_hits and not structural_hits:
        base -= 8.0
    if top_factor == "weak_signal_score":
        base -= 10.0
    if weak > (structural + 20.0):
        base -= 8.0
    if history > 70.0 and structural < 20.0:
        base -= 4.0
    if path_consistency < 20.0 and structural > 50.0:
        base -= 6.0
    if missing:
        base -= 25.0

    score = clip_0_100(base)
    detail = {
        "structural_hits": structural_hits,
        "weak_hits": weak_hits,
        "top_factor": top_factor,
        "missing_origin_or_path": missing,
        "risk_bucket": bucket,
    }
    return score, detail


def calc_conflict_score(row: pd.Series, reasons: list[str]) -> tuple[float, list[str]]:
    structural = safe_num(row.get("structural_novelty_score"))
    weak = safe_num(row.get("weak_signal_score"))
    risk = safe_num(row.get("risk_score"))
    path_consistency = safe_num(row.get("path_consistency_score"))
    top_factor = str(row.get("top_contributing_factor", "") or "")
    bucket = str(row.get("risk_bucket", "low") or "low")
    path_seen_before = bool(row.get("path_seen_before", False))
    missing = bool(row.get("missing_origin_or_path", False))

    unseen_hits = [r for r in reasons if r in {"unseen_origin_for_prefix", "unseen_path_for_prefix_origin", "unseen_exact_path"}]

    flags = []
    score = 0.0

    if structural >= 60.0 and path_consistency < 25.0:
        score += 25.0
        flags.append("high_structural_but_low_path_consistency")
    if weak >= 60.0 and structural < 25.0:
        score += 25.0
        flags.append("strong_weak_signal_but_low_structural")
    if top_factor == "weak_signal_score" and risk >= 35.0 and structural < 30.0:
        score += 15.0
        flags.append("high_risk_driven_by_weak_signal")
    if path_seen_before and len(unseen_hits) >= 2:
        score += 30.0
        flags.append("path_seen_before_with_multiple_unseen_reasons")
    if missing and structural >= 50.0:
        score += 15.0
        flags.append("missing_origin_or_path_with_high_structural")
    if bucket == "high" and structural < 30.0:
        score += 20.0
        flags.append("high_bucket_without_strong_structural")

    return clip_0_100(score), flags


def gate_label(row: pd.Series, certainty: float, conflict: float) -> tuple[str, bool, bool, str]:
    risk_bucket = str(row.get("risk_bucket", "low") or "low")
    structural = safe_num(row.get("structural_novelty_score"))
    weak = safe_num(row.get("weak_signal_score"))
    top_factor = str(row.get("top_contributing_factor", "") or "")
    missing = bool(row.get("missing_origin_or_path", False))

    promoted_from_low = False
    demoted_from_high = False

    if risk_bucket == "high":
        if (
            certainty >= GATING_CONFIG["certainty_threshold_high"]
            and conflict < GATING_CONFIG["conflict_threshold_high"]
            and not missing
            and structural >= 45.0
        ):
            label = "likely_malicious"
            note = "high risk + high certainty + low conflict + non-missing"
        else:
            label = "suspicious_but_uncertain"
            demoted_from_high = True
            note = "high risk but certainty/conflict/missing indicates uncertainty"
    elif risk_bucket == "medium":
        if structural < 20.0 and top_factor in {"weak_signal_score", "history_rarity_score"} and certainty < GATING_CONFIG["certainty_threshold_medium"]:
            label = "likely_benign"
            note = "medium risk but weak-leaning evidence and low certainty"
        else:
            label = "suspicious_but_uncertain"
            note = "medium risk defaults to uncertain pending validation"
    else:
        if (
            structural >= GATING_CONFIG["promote_low_structural_min"]
            and certainty >= GATING_CONFIG["promote_low_certainty_min"]
            and conflict < GATING_CONFIG["conflict_threshold_medium"]
        ):
            label = "suspicious_but_uncertain"
            promoted_from_low = True
            note = "low bucket promoted due strong structural evidence"
        else:
            label = "likely_benign"
            note = "low risk with no strong structural certainty"

    if label == "likely_benign" and weak >= 65.0 and structural < 10.0 and not missing:
        note += "; mostly weak-signal-driven"

    return label, promoted_from_low, demoted_from_high, note


def evaluate_row(row: pd.Series) -> dict:
    reasons = parse_reason_list(row.get("candidate_reasons", "[]"))
    certainty, certainty_detail = calc_certainty_score(row, reasons)
    conflict, conflict_flags = calc_conflict_score(row, reasons)
    label, promoted, demoted, label_note = gate_label(row, certainty, conflict)

    explanation = {
        "label_note": label_note,
        "certainty_score": round(certainty, 4),
        "conflict_score": round(conflict, 4),
        "certainty_detail": certainty_detail,
        "conflict_flags": conflict_flags,
        "reasons": reasons,
    }
    return {
        "certainty_score": round(certainty, 4),
        "conflict_score": round(conflict, 4),
        "gating_label": label,
        "promoted_from_low": bool(promoted),
        "demoted_from_high": bool(demoted),
        "gating_explanation": json.dumps(explanation, ensure_ascii=False),
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
        "risk_score",
        "risk_bucket",
        "certainty_score",
        "conflict_score",
        "gating_label",
        "gating_explanation",
    ]
    for row in df.head(n)[cols].to_dict("records"):
        print("  - " + json.dumps(row, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Uncertainty-aware gating for scored weak candidates.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--scores", default=None, help="Path to scored_candidates.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output directory for gating files.")
    ap.add_argument("--overwrite", type=str2bool, default=False, help="Overwrite existing outputs.")
    args = ap.parse_args()

    if args.scores:
        scores_path = Path(args.scores)
        run_id = args.run_id or infer_run_id(scores_path) or DEFAULT_RUN_ID
    else:
        run_id = args.run_id or DEFAULT_RUN_ID
        scores_path = Path("data") / "runs" / run_id / "scores" / "scored_candidates.parquet"

    if not scores_path.exists():
        raise SystemExit(f"scores file not found: {scores_path}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "gating"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_gated = output_dir / "gated_candidates.parquet"
    out_summary = output_dir / "gating_summary.json"
    if not args.overwrite:
        exists = [p for p in [out_gated, out_summary] if p.exists()]
        if exists:
            raise SystemExit("Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists))

    scored_raw = pd.read_parquet(scores_path)
    scored = ensure_columns(scored_raw)

    eval_df = scored.apply(evaluate_row, axis=1, result_type="expand")
    gated = pd.concat([scored.reset_index(drop=True), eval_df.reset_index(drop=True)], axis=1)

    output_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "top_contributing_factor",
        "matched_rule_count",
        "missing_origin_or_path",
        "certainty_score",
        "conflict_score",
        "gating_label",
        "gating_explanation",
        "promoted_from_low",
        "demoted_from_high",
        "candidate_reasons",
        "path_seen_before",
    ]
    output_df = gated[output_cols].copy()
    output_df.to_parquet(out_gated, index=False)

    label_counts = output_df["gating_label"].value_counts().to_dict()
    label_counts = {str(k): int(v) for k, v in label_counts.items()}
    likely_malicious_count = int(label_counts.get("likely_malicious", 0))
    uncertain_count = int(label_counts.get("suspicious_but_uncertain", 0))
    benign_count = int(label_counts.get("likely_benign", 0))
    avg_certainty = float(output_df["certainty_score"].mean()) if len(output_df) else 0.0
    avg_conflict = float(output_df["conflict_score"].mean()) if len(output_df) else 0.0
    missing_count = int(output_df["missing_origin_or_path"].sum())
    promoted_count = int(output_df["promoted_from_low"].sum())
    demoted_count = int(output_df["demoted_from_high"].sum())

    malicious_top_factor = (
        output_df[output_df["gating_label"] == "likely_malicious"]["top_contributing_factor"].value_counts().to_dict()
    )
    malicious_top_factor = {str(k): int(v) for k, v in malicious_top_factor.items()}

    summary = {
        "run_id": run_id,
        "scores_path": to_rel_path(scores_path),
        "output_gated_path": to_rel_path(out_gated),
        "output_summary_path": to_rel_path(out_summary),
        "input_rows": int(len(scored)),
        "label_counts": label_counts,
        "likely_malicious_count": likely_malicious_count,
        "suspicious_but_uncertain_count": uncertain_count,
        "likely_benign_count": benign_count,
        "avg_certainty_score": avg_certainty,
        "avg_conflict_score": avg_conflict,
        "missing_origin_or_path_count": missing_count,
        "promoted_from_low_count": promoted_count,
        "demoted_from_high_count": demoted_count,
        "likely_malicious_top_contributing_factor": malicious_top_factor,
        "gating_config": GATING_CONFIG,
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_scores: {to_rel_path(scores_path)}")
    print(f"input_rows: {len(scored)}")
    print(f"likely_malicious: {likely_malicious_count}")
    print(f"suspicious_but_uncertain: {uncertain_count}")
    print(f"likely_benign: {benign_count}")
    print(f"avg_certainty_score: {avg_certainty:.4f}")
    print(f"avg_conflict_score: {avg_conflict:.4f}")
    print(f"missing_origin_or_path: {missing_count}")
    print(f"output_gated_path: {to_rel_path(out_gated)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")

    print_samples(output_df[output_df["gating_label"] == "likely_malicious"], "likely_malicious_samples", 10)
    print_samples(output_df[output_df["gating_label"] == "suspicious_but_uncertain"], "suspicious_but_uncertain_samples", 10)
    print_samples(output_df[output_df["gating_label"] == "likely_benign"], "likely_benign_samples", 10)
    print_samples(output_df[output_df["demoted_from_high"]], "demoted_from_high_samples", 5)
    print_samples(output_df[output_df["promoted_from_low"]], "promoted_from_low_samples", 5)


if __name__ == "__main__":
    main()
