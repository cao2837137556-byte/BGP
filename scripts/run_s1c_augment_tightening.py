import argparse
import json
from pathlib import Path

import pandas as pd


QUALITY_THRESHOLDS = {
    "clean_certainty_min": 80.0,
    "noisy_conflict_min": 5.0,
    "noisy_certainty_max_exclusive": 60.0,
}

PROMOTED_THRESHOLD_DEFAULT = 65.0
PROMOTED_THRESHOLD_A3 = 70.0


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    lowered = series.astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y", "on"})


def read_final(path: Path) -> pd.DataFrame:
    cols = [
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
        "missing_origin_or_path",
        "certainty_score",
        "conflict_score",
        "evidence_support_score",
    ]
    df = pd.read_parquet(path, columns=cols)
    df["event_id"] = df["event_id"].fillna("").astype(str)
    df["gating_label"] = df["gating_label"].fillna("").astype(str)
    df["augmentation_label"] = df["augmentation_label"].fillna("").astype(str)
    df["final_alert_label"] = df["final_alert_label"].fillna("").astype(str)
    df["alert_source_layer"] = df["alert_source_layer"].fillna("").astype(str)
    df["top_contributing_factor"] = df["top_contributing_factor"].fillna("").astype(str)
    df["candidate_reasons"] = df["candidate_reasons"].fillna("[]").astype(str)
    df["certainty_score"] = pd.to_numeric(df["certainty_score"], errors="coerce").fillna(0.0)
    df["conflict_score"] = pd.to_numeric(df["conflict_score"], errors="coerce").fillna(0.0)
    df["risk_score"] = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0.0)
    df["evidence_support_score"] = pd.to_numeric(df["evidence_support_score"], errors="coerce")
    df["missing_origin_or_path"] = to_bool_series(df["missing_origin_or_path"])
    return df


def read_augmentation(path: Path) -> pd.DataFrame:
    cols = [
        "event_id",
        "augmentation_label",
        "evidence_support_score",
        "certainty_score",
        "conflict_score",
        "risk_score",
        "gating_label",
        "promoted_from_uncertain",
        "demoted_from_uncertain",
        "route_leak_review_preserved",
    ]
    df = pd.read_parquet(path, columns=cols)
    df["event_id"] = df["event_id"].fillna("").astype(str)
    df["augmentation_label"] = df["augmentation_label"].fillna("").astype(str)
    df["evidence_support_score"] = pd.to_numeric(df["evidence_support_score"], errors="coerce")
    df["certainty_score"] = pd.to_numeric(df["certainty_score"], errors="coerce").fillna(0.0)
    df["conflict_score"] = pd.to_numeric(df["conflict_score"], errors="coerce").fillna(0.0)
    df["risk_score"] = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0.0)
    df["gating_label"] = df["gating_label"].fillna("").astype(str)
    df["promoted_from_uncertain"] = to_bool_series(df["promoted_from_uncertain"])
    df["demoted_from_uncertain"] = to_bool_series(df["demoted_from_uncertain"])
    df["route_leak_review_preserved"] = to_bool_series(df["route_leak_review_preserved"])
    return df


def classify_quality_bucket(df: pd.DataFrame) -> pd.Series:
    clean_mask = (
        (~df["missing_origin_or_path"])
        & (df["conflict_score"] == 0.0)
        & (df["certainty_score"] >= QUALITY_THRESHOLDS["clean_certainty_min"])
    )
    noisy_mask = (
        df["missing_origin_or_path"]
        | (df["conflict_score"] >= QUALITY_THRESHOLDS["noisy_conflict_min"])
        | (df["certainty_score"] < QUALITY_THRESHOLDS["noisy_certainty_max_exclusive"])
    )
    out = pd.Series("fragile-high", index=df.index, dtype="object")
    out.loc[noisy_mask] = "noisy-high"
    out.loc[clean_mask] = "clean-high"
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
    return "needs_review", "fallback_uncertain"


def apply_variant(aug_df: pd.DataFrame, variant: str, threshold: float) -> pd.DataFrame:
    out = aug_df.copy()
    current_promoted = out["augmentation_label"].eq("promoted_suspicious")
    block_mask = pd.Series(False, index=out.index)

    if variant == "A1_missing_block":
        block_mask = current_promoted & out["missing_origin_or_path"]
    elif variant == "A2_missing_or_conflict_block":
        block_mask = current_promoted & (out["missing_origin_or_path"] | (out["conflict_score"] > 0.0))
    elif variant == "A3_missing_block_plus_threshold70":
        block_mask = current_promoted & (
            out["missing_origin_or_path"] | (out["evidence_support_score"].fillna(0.0) < threshold)
        )
    elif variant == "R0_reference":
        block_mask = pd.Series(False, index=out.index)
    else:
        raise ValueError(f"unknown variant: {variant}")

    out["variant_augmentation_label"] = out["augmentation_label"]
    out.loc[block_mask, "variant_augmentation_label"] = "retained_uncertain"
    out["variant_blocked_from_promotion"] = block_mask
    return out


def build_variant_final(
    final_ref: pd.DataFrame,
    aug_variant: pd.DataFrame,
    variant: str,
) -> pd.DataFrame:
    aug_small = aug_variant[
        ["event_id", "variant_augmentation_label", "variant_blocked_from_promotion", "evidence_support_score"]
    ].copy()
    merged = final_ref.merge(aug_small, on="event_id", how="left")
    merged["variant"] = variant
    merged["variant_augmentation_label"] = merged["variant_augmentation_label"].fillna(merged["augmentation_label"]).astype(str)
    blocked = merged["variant_blocked_from_promotion"]
    blocked = blocked.where(blocked.notna(), False)
    merged["variant_blocked_from_promotion"] = to_bool_series(blocked)

    decisions = merged.apply(
        lambda row: decide_final_label(row.get("gating_label", ""), row.get("variant_augmentation_label", "")),
        axis=1,
        result_type="expand",
    )
    merged["final_alert_label"] = decisions[0]
    merged["alert_source_layer"] = decisions[1]
    merged["augmentation_label"] = merged["variant_augmentation_label"]
    merged["quality_bucket"] = ""
    high_mask = merged["final_alert_label"].eq("high_priority_alert")
    if high_mask.any():
        merged.loc[high_mask, "quality_bucket"] = classify_quality_bucket(merged.loc[high_mask]).astype(str)
    return merged


def summarize_variant(
    variant_df: pd.DataFrame,
    variant: str,
    r0_gating_high_ids: set[str],
    r0_aug_noisy_high_ids: set[str],
) -> dict:
    total_high = int((variant_df["final_alert_label"] == "high_priority_alert").sum())
    total_needs = int((variant_df["final_alert_label"] == "needs_review").sum())
    total_low = int((variant_df["final_alert_label"] == "low_priority_or_background").sum())

    high_df = variant_df[variant_df["final_alert_label"] == "high_priority_alert"].copy()
    clean_count = int((high_df["quality_bucket"] == "clean-high").sum())
    fragile_count = int((high_df["quality_bucket"] == "fragile-high").sum())
    noisy_count = int((high_df["quality_bucket"] == "noisy-high").sum())

    aug_promoted_total = int(variant_df["augmentation_label"].eq("promoted_suspicious").sum())
    aug_promoted_to_high = int(
        ((variant_df["augmentation_label"] == "promoted_suspicious") & (variant_df["final_alert_label"] == "high_priority_alert")).sum()
    )
    gating_likely_malicious_to_high = int(
        ((variant_df["alert_source_layer"] == "gating_likely_malicious") & (variant_df["final_alert_label"] == "high_priority_alert")).sum()
    )
    noisy_high_from_augment = int(
        (
            (variant_df["final_alert_label"] == "high_priority_alert")
            & (variant_df["quality_bucket"] == "noisy-high")
            & (variant_df["alert_source_layer"] == "augmentation_promoted")
        ).sum()
    )

    current_gating_high_ids = set(
        variant_df.loc[
            (variant_df["final_alert_label"] == "high_priority_alert")
            & (variant_df["alert_source_layer"] == "gating_likely_malicious"),
            "event_id",
        ].astype(str)
    )
    retained_r0_gating_high_ratio = (
        len(r0_gating_high_ids & current_gating_high_ids) / len(r0_gating_high_ids) if r0_gating_high_ids else 0.0
    )
    needs_from_r0_aug_noisy = int(
        variant_df.loc[
            variant_df["event_id"].astype(str).isin(r0_aug_noisy_high_ids)
            & variant_df["final_alert_label"].eq("needs_review")
        ].shape[0]
    )
    r0_aug_noisy_to_needs_ratio = (
        needs_from_r0_aug_noisy / len(r0_aug_noisy_high_ids) if r0_aug_noisy_high_ids else 0.0
    )

    return {
        "variant": variant,
        "final_high": total_high,
        "final_needs": total_needs,
        "final_low": total_low,
        "high_certainty_mean": float(high_df["certainty_score"].mean()) if len(high_df) else 0.0,
        "high_conflict_mean": float(high_df["conflict_score"].mean()) if len(high_df) else 0.0,
        "high_missing_rate": float(high_df["missing_origin_or_path"].mean()) if len(high_df) else 0.0,
        "clean_high": clean_count,
        "fragile_high": fragile_count,
        "noisy_high": noisy_count,
        "augmentation_promoted_total": aug_promoted_total,
        "augmentation_promoted_to_high": aug_promoted_to_high,
        "gating_likely_malicious_to_high": gating_likely_malicious_to_high,
        "noisy_high_augment_source_count": noisy_high_from_augment,
        "r0_gating_high_retained_ratio": retained_r0_gating_high_ratio,
        "r0_augment_noisy_high_to_needs_ratio": r0_aug_noisy_to_needs_ratio,
        "variant_blocked_from_promotion_count": int(variant_df["variant_blocked_from_promotion"].sum()),
    }


def build_quality_bucket_rows(variant_df: pd.DataFrame, variant: str) -> pd.DataFrame:
    high_df = variant_df[variant_df["final_alert_label"] == "high_priority_alert"].copy()
    rows = []
    for bucket in ["clean-high", "fragile-high", "noisy-high"]:
        sub = high_df[high_df["quality_bucket"] == bucket]
        rows.append(
            {
                "variant": variant,
                "quality_bucket": bucket,
                "count": int(len(sub)),
                "pct_within_high": float(len(sub) / len(high_df)) if len(high_df) else 0.0,
                "certainty_mean": float(sub["certainty_score"].mean()) if len(sub) else 0.0,
                "conflict_mean": float(sub["conflict_score"].mean()) if len(sub) else 0.0,
                "missing_rate": float(sub["missing_origin_or_path"].mean()) if len(sub) else 0.0,
                "augment_source_count": int((sub["alert_source_layer"] == "augmentation_promoted").sum()),
                "gate_source_count": int((sub["alert_source_layer"] == "gating_likely_malicious").sum()),
            }
        )
    return pd.DataFrame(rows)


def build_source_bucket_rows(variant_df: pd.DataFrame, variant: str) -> pd.DataFrame:
    high_df = variant_df[variant_df["final_alert_label"] == "high_priority_alert"].copy()
    rows = []
    total_high = len(high_df)

    for analysis_view, column in [
        ("alert_source_layer", "alert_source_layer"),
        ("gating_label", "gating_label"),
        ("augmentation_label", "augmentation_label"),
        ("top_contributing_factor", "top_contributing_factor"),
    ]:
        grouped = (
            high_df.groupby(column, dropna=False).size().reset_index(name="count").sort_values("count", ascending=False)
        )
        for item in grouped.to_dict("records"):
            rows.append(
                {
                    "variant": variant,
                    "analysis_view": analysis_view,
                    "bucket_value": item[column],
                    "count": int(item["count"]),
                    "pct_within_high": float(item["count"] / total_high) if total_high else 0.0,
                }
            )

    noisy_high = high_df[high_df["quality_bucket"] == "noisy-high"].copy()
    noisy_total = len(noisy_high)
    grouped_noisy = (
        noisy_high.groupby(
            ["alert_source_layer", "gating_label", "augmentation_label", "top_contributing_factor"], dropna=False
        )
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    for item in grouped_noisy.to_dict("records"):
        rows.append(
            {
                "variant": variant,
                "analysis_view": "noisy_high_combined",
                "bucket_value": json.dumps(
                    {
                        "alert_source_layer": item["alert_source_layer"],
                        "gating_label": item["gating_label"],
                        "augmentation_label": item["augmentation_label"],
                        "top_contributing_factor": item["top_contributing_factor"],
                    },
                    ensure_ascii=False,
                ),
                "count": int(item["count"]),
                "pct_within_high": float(item["count"] / total_high) if total_high else 0.0,
                "pct_within_noisy_high": float(item["count"] / noisy_total) if noisy_total else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_report(
    output_path: Path,
    results_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    source_df: pd.DataFrame,
) -> None:
    r0 = results_df.set_index("variant").loc["R0_reference"]
    best = results_df.sort_values(
        ["noisy_high", "high_missing_rate", "gating_likely_malicious_to_high"],
        ascending=[True, True, False],
    ).iloc[0]

    lines = []
    lines.append("# S1-C Modern Augment Tightening")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append("- upstream reused: S1-A expanded `gating` + `augmentation` + `final` outputs")
    lines.append("- no rerun of events / baseline / candidate / score / gate")
    lines.append("- quality buckets fixed from S1-B")
    lines.append("- variant alignment key: `event_id` within the same expanded run")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    for row in results_df.to_dict("records"):
        lines.append(
            f"- {row['variant']}: high={row['final_high']}, needs={row['final_needs']}, low={row['final_low']}, "
            f"missing_rate={row['high_missing_rate']:.4f}, conflict_mean={row['high_conflict_mean']:.4f}, "
            f"augment_to_high={row['augmentation_promoted_to_high']}"
        )
    lines.append("")
    lines.append("## Best Variant")
    lines.append("")
    lines.append(
        f"- best_variant={best['variant']} "
        f"(noisy_high={int(best['noisy_high'])}, high_missing_rate={best['high_missing_rate']:.4f}, "
        f"gating_high={int(best['gating_likely_malicious_to_high'])})"
    )
    lines.append("")
    lines.append("## Delta vs R0")
    lines.append("")
    for row in results_df.to_dict("records"):
        if row["variant"] == "R0_reference":
            continue
        lines.append(
            f"- {row['variant']}: high_delta={int(row['high_delta_vs_R0'])}, "
            f"noisy_delta={int(row['noisy_high_delta_vs_R0'])}, "
            f"augment_to_high_delta={int(row['augmentation_promoted_to_high_delta_vs_R0'])}, "
            f"r0_gating_high_retained_ratio={row['r0_gating_high_retained_ratio']:.4f}, "
            f"r0_aug_noisy_to_needs_ratio={row['r0_augment_noisy_high_to_needs_ratio']:.4f}"
        )
    lines.append("")
    lines.append("## Noisy-high Source Snapshot")
    lines.append("")
    noisy_top = source_df[source_df["analysis_view"] == "noisy_high_combined"].groupby("variant", sort=False).head(3)
    for row in noisy_top.to_dict("records"):
        lines.append(
            f"- {row['variant']}: count={row['count']}, pct_noisy={row.get('pct_within_noisy_high', 0.0):.4f}, bucket={row['bucket_value']}"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="S1-C modern augment tightening variants")
    ap.add_argument("--output-dir", default="outputs/s1c_augment_tightening_v01")
    ap.add_argument(
        "--expanded-final",
        default="data/runs/s1a_expanded_v02_pilot_60m_april16/final/final_alerts.parquet",
    )
    ap.add_argument(
        "--expanded-augmentation",
        default="data/runs/s1a_expanded_v02_pilot_60m_april16/augmentation/augmented_candidates.parquet",
    )
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    final_ref = read_final(Path(args.expanded_final))
    aug_df = read_augmentation(Path(args.expanded_augmentation))
    aug_df = aug_df.merge(
        final_ref[["event_id", "missing_origin_or_path"]],
        on="event_id",
        how="left",
    )
    aug_df["missing_origin_or_path"] = to_bool_series(aug_df["missing_origin_or_path"])
    final_ref = final_ref.merge(
        aug_df[["event_id", "evidence_support_score"]],
        on="event_id",
        how="left",
        suffixes=("", "_aug"),
    )
    final_ref["evidence_support_score"] = final_ref["evidence_support_score"].fillna(final_ref["evidence_support_score_aug"])
    final_ref = final_ref.drop(columns=[c for c in final_ref.columns if c.endswith("_aug")])

    variants = [
        ("R0_reference", PROMOTED_THRESHOLD_DEFAULT),
        ("A1_missing_block", PROMOTED_THRESHOLD_DEFAULT),
        ("A2_missing_or_conflict_block", PROMOTED_THRESHOLD_DEFAULT),
        ("A3_missing_block_plus_threshold70", PROMOTED_THRESHOLD_A3),
    ]

    variant_frames = {}
    results_rows = []
    quality_frames = []
    source_frames = []

    r0_gating_high_ids = set()
    r0_aug_noisy_high_ids = set()

    for variant_name, threshold in variants:
        aug_variant = apply_variant(aug_df, variant_name, threshold)
        variant_final = build_variant_final(final_ref, aug_variant, variant_name)
        variant_frames[variant_name] = variant_final

        if variant_name == "R0_reference":
            r0_gating_high_ids = set(
                variant_final.loc[
                    (variant_final["final_alert_label"] == "high_priority_alert")
                    & (variant_final["alert_source_layer"] == "gating_likely_malicious"),
                    "event_id",
                ].astype(str)
            )
            r0_aug_noisy_high_ids = set(
                variant_final.loc[
                    (variant_final["final_alert_label"] == "high_priority_alert")
                    & (variant_final["alert_source_layer"] == "augmentation_promoted")
                    & (variant_final["quality_bucket"] == "noisy-high"),
                    "event_id",
                ].astype(str)
            )

    for variant_name, _ in variants:
        variant_final = variant_frames[variant_name]
        results_rows.append(
            summarize_variant(
                variant_final,
                variant_name,
                r0_gating_high_ids=r0_gating_high_ids,
                r0_aug_noisy_high_ids=r0_aug_noisy_high_ids,
            )
        )
        quality_frames.append(build_quality_bucket_rows(variant_final, variant_name))
        source_frames.append(build_source_bucket_rows(variant_final, variant_name))

        if variant_name != "R0_reference":
            variant_path = output_dir / f"s1c_variant_{variant_name.replace('A', 'A').replace('R0_reference', 'R0')}_final_alerts.parquet"
            variant_final.to_parquet(variant_path, index=False)

    results_df = pd.DataFrame(results_rows)
    r0 = results_df.set_index("variant").loc["R0_reference"]
    results_df["high_delta_vs_R0"] = results_df["final_high"] - int(r0["final_high"])
    results_df["high_reduction_ratio_vs_R0"] = 1.0 - (results_df["final_high"] / float(r0["final_high"]))
    results_df["noisy_high_delta_vs_R0"] = results_df["noisy_high"] - int(r0["noisy_high"])
    results_df["augmentation_promoted_to_high_delta_vs_R0"] = (
        results_df["augmentation_promoted_to_high"] - int(r0["augmentation_promoted_to_high"])
    )
    results_df = results_df[
        [
            "variant",
            "final_high",
            "final_needs",
            "final_low",
            "high_certainty_mean",
            "high_conflict_mean",
            "high_missing_rate",
            "clean_high",
            "fragile_high",
            "noisy_high",
            "augmentation_promoted_total",
            "augmentation_promoted_to_high",
            "gating_likely_malicious_to_high",
            "noisy_high_augment_source_count",
            "r0_gating_high_retained_ratio",
            "r0_augment_noisy_high_to_needs_ratio",
            "variant_blocked_from_promotion_count",
            "high_delta_vs_R0",
            "high_reduction_ratio_vs_R0",
            "noisy_high_delta_vs_R0",
            "augmentation_promoted_to_high_delta_vs_R0",
        ]
    ]

    quality_df = pd.concat(quality_frames, ignore_index=True)
    source_df = pd.concat(source_frames, ignore_index=True)

    results_df.to_csv(output_dir / "s1c_augment_tightening_results.csv", index=False, encoding="utf-8-sig")
    quality_df.to_csv(output_dir / "s1c_augment_tightening_quality_buckets.csv", index=False, encoding="utf-8-sig")
    source_df.to_csv(output_dir / "s1c_augment_tightening_source_buckets.csv", index=False, encoding="utf-8-sig")
    build_report(output_dir / "s1c_augment_tightening_report.md", results_df, quality_df, source_df)

    print(f"output_dir={output_dir}")
    for row in results_df.to_dict("records"):
        print(
            f"{row['variant']}: high={row['final_high']} needs={row['final_needs']} low={row['final_low']} "
            f"missing_rate={row['high_missing_rate']:.4f} noisy={row['noisy_high']} "
            f"augment_to_high={row['augmentation_promoted_to_high']} gating_high={row['gating_likely_malicious_to_high']}"
        )


if __name__ == "__main__":
    main()
