import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_RUN_ID = "20260313T032554_4f9be28c"


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


def safe_num(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def ensure_scores_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "event_id": "",
        "run_id": "",
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "risk_score": 0.0,
        "risk_bucket": "low",
        "top_contributing_factor": "",
        "candidate_reasons": "[]",
        "missing_origin_or_path": False,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    text_cols = [
        "event_id",
        "run_id",
        "prefix",
        "as_path_clean",
        "risk_bucket",
        "top_contributing_factor",
        "candidate_reasons",
    ]
    for col in text_cols:
        out[col] = out[col].fillna("").astype(str)

    out["risk_score"] = pd.to_numeric(out["risk_score"], errors="coerce").fillna(0.0)
    out["origin_as"] = pd.to_numeric(out["origin_as"], errors="coerce")
    if out["missing_origin_or_path"].dtype != bool:
        out["missing_origin_or_path"] = out["missing_origin_or_path"].fillna(False).astype(bool)
    return out


def ensure_gating_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "event_id": "",
        "gating_label": "",
        "gating_explanation": "",
        "certainty_score": 0.0,
        "conflict_score": 0.0,
        "missing_origin_or_path": False,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    out["event_id"] = out["event_id"].fillna("").astype(str)
    out["gating_label"] = out["gating_label"].fillna("").astype(str)
    out["gating_explanation"] = out["gating_explanation"].fillna("").astype(str)
    out["certainty_score"] = pd.to_numeric(out["certainty_score"], errors="coerce").fillna(0.0)
    out["conflict_score"] = pd.to_numeric(out["conflict_score"], errors="coerce").fillna(0.0)
    if out["missing_origin_or_path"].dtype != bool:
        out["missing_origin_or_path"] = out["missing_origin_or_path"].fillna(False).astype(bool)
    return out


def ensure_augmentation_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "event_id": "",
        "augmentation_label": "",
        "augmentation_explanation": "",
        "evidence_support_score": None,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    out["event_id"] = out["event_id"].fillna("").astype(str)
    out["augmentation_label"] = out["augmentation_label"].fillna("").astype(str)
    out["augmentation_explanation"] = out["augmentation_explanation"].fillna("").astype(str)
    out["evidence_support_score"] = pd.to_numeric(out["evidence_support_score"], errors="coerce")
    return out


def decide_final_label(gating_label: str, augmentation_label: str) -> tuple[str, str]:
    g = (gating_label or "").strip()
    a = (augmentation_label or "").strip()

    if a == "promoted_suspicious":
        return "high_priority_alert", "augmentation_promoted"
    if g == "likely_malicious":
        return "high_priority_alert", "gating_likely_malicious"

    if a == "demoted_suspicious":
        return "low_priority_or_background", "augmentation_demoted"
    if g == "likely_benign":
        return "low_priority_or_background", "gating_likely_benign"

    if g == "suspicious_but_uncertain" and (a == "retained_uncertain" or a == ""):
        return "needs_review", "gating_uncertain"

    # defensive fallback
    return "needs_review", "fallback_uncertain"


def print_samples(df: pd.DataFrame, label: str, n: int):
    print(f"{label}_samples:")
    if df.empty:
        print("  <empty>")
        return
    cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "gating_label",
        "augmentation_label",
        "final_alert_label",
        "top_contributing_factor",
    ]
    for row in df.head(n)[cols].to_dict("records"):
        print("  - " + json.dumps(row, ensure_ascii=False))


def mean_by_label(df: pd.DataFrame, value_col: str, label_col: str = "final_alert_label") -> dict:
    if value_col not in df.columns:
        return {}
    rows = []
    for label, grp in df.groupby(label_col, dropna=False):
        val = pd.to_numeric(grp[value_col], errors="coerce").dropna()
        rows.append((str(label), float(val.mean()) if len(val) else None))
    return {k: v for k, v in rows}


def main():
    ap = argparse.ArgumentParser(description="Build unified final alerts from gating + augmentation + scores outputs.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--gating", default=None, help="Path to gated_candidates.parquet.")
    ap.add_argument("--augmentation", default=None, help="Path to augmented_candidates.parquet.")
    ap.add_argument("--scores", default=None, help="Path to scored_candidates.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output directory for final artifacts.")
    ap.add_argument("--overwrite", type=str2bool, default=False, help="Overwrite existing outputs.")
    args = ap.parse_args()

    if args.scores:
        scores_path = Path(args.scores)
        run_id = args.run_id or infer_run_id(scores_path) or DEFAULT_RUN_ID
    else:
        run_id = args.run_id or DEFAULT_RUN_ID
        scores_path = Path("data") / "runs" / run_id / "scores" / "scored_candidates.parquet"

    gating_path = Path(args.gating) if args.gating else Path("data") / "runs" / run_id / "gating" / "gated_candidates.parquet"
    augmentation_path = (
        Path(args.augmentation)
        if args.augmentation
        else Path("data") / "runs" / run_id / "augmentation" / "augmented_candidates.parquet"
    )

    for p in [scores_path, gating_path, augmentation_path]:
        if not p.exists():
            raise SystemExit(f"required input file not found: {p}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "final"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_parquet = output_dir / "final_alerts.parquet"
    out_report = output_dir / "final_report.json"
    if not args.overwrite:
        exists = [p for p in [out_parquet, out_report] if p.exists()]
        if exists:
            raise SystemExit("Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists))

    scores_df = ensure_scores_columns(pd.read_parquet(scores_path))
    gating_df = ensure_gating_columns(pd.read_parquet(gating_path))
    aug_df = ensure_augmentation_columns(pd.read_parquet(augmentation_path))

    total_scored_rows = int(len(scores_df))
    total_gated_rows = int(len(gating_df))
    total_augmented_rows = int(len(aug_df))

    final_df = scores_df.merge(
        gating_df[
            [
                "event_id",
                "gating_label",
                "gating_explanation",
                "certainty_score",
                "conflict_score",
                "missing_origin_or_path",
            ]
        ].rename(columns={"missing_origin_or_path": "gating_missing_origin_or_path"}),
        on="event_id",
        how="left",
    )
    final_df = final_df.merge(
        aug_df[
            [
                "event_id",
                "augmentation_label",
                "augmentation_explanation",
                "evidence_support_score",
            ]
        ],
        on="event_id",
        how="left",
    )

    final_df["gating_label"] = final_df["gating_label"].fillna("").astype(str)
    final_df["augmentation_label"] = final_df["augmentation_label"].fillna("").astype(str)
    final_df["gating_explanation"] = final_df["gating_explanation"].fillna("").astype(str)
    final_df["augmentation_explanation"] = final_df["augmentation_explanation"].fillna("").astype(str)
    final_df["certainty_score"] = pd.to_numeric(final_df["certainty_score"], errors="coerce").fillna(0.0)
    final_df["conflict_score"] = pd.to_numeric(final_df["conflict_score"], errors="coerce").fillna(0.0)
    final_df["evidence_support_score"] = pd.to_numeric(final_df["evidence_support_score"], errors="coerce")
    final_df["gating_missing_origin_or_path"] = final_df["gating_missing_origin_or_path"].fillna(False).astype(bool)
    final_df["missing_origin_or_path"] = final_df["missing_origin_or_path"] | final_df["gating_missing_origin_or_path"]

    decision = final_df.apply(
        lambda r: decide_final_label(r.get("gating_label", ""), r.get("augmentation_label", "")),
        axis=1,
        result_type="expand",
    )
    final_df["final_alert_label"] = decision[0]
    final_df["alert_source_layer"] = decision[1]

    output_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "gating_label",
        "augmentation_label",
        "final_alert_label",
        "alert_source_layer",
        "top_contributing_factor",
        "candidate_reasons",
        "gating_explanation",
        "augmentation_explanation",
        "missing_origin_or_path",
        "certainty_score",
        "conflict_score",
        "evidence_support_score",
    ]
    out_df = final_df[output_cols].copy()
    out_df.to_parquet(out_parquet, index=False)

    label_counts = out_df["final_alert_label"].value_counts().to_dict()
    label_counts = {str(k): int(v) for k, v in label_counts.items()}
    high_priority_alert_count = int(label_counts.get("high_priority_alert", 0))
    needs_review_count = int(label_counts.get("needs_review", 0))
    low_priority_or_background_count = int(label_counts.get("low_priority_or_background", 0))

    high_priority_from_gating_count = int(
        ((out_df["final_alert_label"] == "high_priority_alert") & (out_df["alert_source_layer"] == "gating_likely_malicious")).sum()
    )
    high_priority_from_augmentation_count = int(
        ((out_df["final_alert_label"] == "high_priority_alert") & (out_df["alert_source_layer"] == "augmentation_promoted")).sum()
    )
    missing_origin_or_path_in_high_priority = int(
        ((out_df["final_alert_label"] == "high_priority_alert") & (out_df["missing_origin_or_path"])).sum()
    )

    report = {
        "run_id": run_id,
        "scores_path": to_rel_path(scores_path),
        "gating_path": to_rel_path(gating_path),
        "augmentation_path": to_rel_path(augmentation_path),
        "output_final_alerts_path": to_rel_path(out_parquet),
        "output_final_report_path": to_rel_path(out_report),
        "total_scored_rows": total_scored_rows,
        "total_gated_rows": total_gated_rows,
        "total_augmented_rows": total_augmented_rows,
        "high_priority_alert_count": high_priority_alert_count,
        "needs_review_count": needs_review_count,
        "low_priority_or_background_count": low_priority_or_background_count,
        "high_priority_from_gating_count": high_priority_from_gating_count,
        "high_priority_from_augmentation_count": high_priority_from_augmentation_count,
        "missing_origin_or_path_in_high_priority": missing_origin_or_path_in_high_priority,
        "avg_risk_score_by_final_label": mean_by_label(out_df, "risk_score"),
        "avg_evidence_support_by_final_label": mean_by_label(out_df, "evidence_support_score"),
    }
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"scores_path: {to_rel_path(scores_path)}")
    print(f"gating_path: {to_rel_path(gating_path)}")
    print(f"augmentation_path: {to_rel_path(augmentation_path)}")
    print(f"total_scored_rows: {total_scored_rows}")
    print(f"high_priority_alert: {high_priority_alert_count}")
    print(f"needs_review: {needs_review_count}")
    print(f"low_priority_or_background: {low_priority_or_background_count}")
    print(f"output_final_alerts_path: {to_rel_path(out_parquet)}")
    print(f"output_final_report_path: {to_rel_path(out_report)}")

    print_samples(out_df[out_df["final_alert_label"] == "high_priority_alert"], "high_priority_alert", 10)
    print_samples(out_df[out_df["final_alert_label"] == "needs_review"], "needs_review", 10)
    print_samples(out_df[out_df["final_alert_label"] == "low_priority_or_background"], "low_priority_or_background", 10)


if __name__ == "__main__":
    main()
