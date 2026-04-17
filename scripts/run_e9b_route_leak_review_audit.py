import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_GOOGLE_RUN_ID = "e9a_expanded_v01_google_verizon_20170825"
DEFAULT_CONTROL_RUN_IDS = [
    "e9a_expanded_v01_rostelecom_20170426",
    "e9a_expanded_v01_route53_mew_20180424",
]
DEFAULT_OUTPUT_DIR = "outputs/e9b_route_leak_review_audit_v01"
TARGET_PREFIX = "114.154.133.0/24"


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def label_counts(df: pd.DataFrame, label_col: str) -> dict[str, int]:
    if df.empty or label_col not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df[label_col].value_counts().to_dict().items()}


def google_target_rows(base: Path, run_id: str) -> pd.DataFrame:
    final_df = read_parquet(base / "data" / "runs" / run_id / "final" / "final_alerts.parquet")
    if final_df.empty:
        return pd.DataFrame()
    mask = final_df["prefix"].astype(str).eq(TARGET_PREFIX)
    cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "certainty_score",
        "conflict_score",
        "gating_label",
        "augmentation_label",
        "final_alert_label",
    ]
    keep = [c for c in cols if c in final_df.columns]
    return final_df.loc[mask, keep].copy()


def audit_google_run(base: Path, run_id: str) -> tuple[dict, pd.DataFrame]:
    run_dir = base / "data" / "runs" / run_id
    gate_df = read_parquet(run_dir / "gating" / "gated_candidates.parquet")
    aug_df = read_parquet(run_dir / "augmentation" / "augmented_candidates.parquet")
    final_df = read_parquet(run_dir / "final" / "final_alerts.parquet")

    if aug_df.empty:
        raise SystemExit(f"augmentation parquet missing or empty: {run_dir / 'augmentation' / 'augmented_candidates.parquet'}")

    preserved_mask = aug_df.get("route_leak_review_preserved", pd.Series(False, index=aug_df.index)).fillna(False).astype(bool)
    preserved_df = aug_df.loc[preserved_mask].copy()
    preserved_event_ids = set(preserved_df["event_id"].astype(str).tolist())
    preserved_final = final_df[final_df["event_id"].astype(str).isin(preserved_event_ids)].copy() if not final_df.empty else pd.DataFrame()

    target_final = google_target_rows(base, run_id)

    gating_target = pd.DataFrame()
    if not gate_df.empty and "prefix" in gate_df.columns:
        gating_target = gate_df[gate_df["prefix"].astype(str).eq(TARGET_PREFIX)].copy()

    summary = {
        "run_id": run_id,
        "target_prefix": TARGET_PREFIX,
        "target_event_count": int(len(target_final)),
        "target_final_label_counts": label_counts(target_final, "final_alert_label"),
        "target_gating_label_counts": label_counts(gating_target, "gating_label"),
        "route_leak_review_preserved_rows": int(len(preserved_df)),
        "route_leak_review_preserved_prefixes": int(preserved_df["prefix"].astype(str).nunique()) if not preserved_df.empty else 0,
        "route_leak_review_preserved_origins": int(pd.to_numeric(preserved_df["origin_as"], errors="coerce").nunique()) if not preserved_df.empty else 0,
        "route_leak_review_preserved_target_rows": int((preserved_df["prefix"].astype(str) == TARGET_PREFIX).sum()) if not preserved_df.empty else 0,
        "route_leak_review_preserved_final_label_counts": label_counts(preserved_final, "final_alert_label"),
        "google_target_matched_event_ids": target_final["event_id"].astype(str).tolist() if not target_final.empty else [],
    }
    return summary, preserved_df


def audit_control_runs(base: Path, run_ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for run_id in run_ids:
        aug_df = read_parquet(base / "data" / "runs" / run_id / "augmentation" / "augmented_candidates.parquet")
        preserved = 0
        if not aug_df.empty and "route_leak_review_preserved" in aug_df.columns:
            preserved = int(aug_df["route_leak_review_preserved"].fillna(False).astype(bool).sum())
        rows.append({"run_id": run_id, "route_leak_review_preserved_rows": preserved})
    return rows


def build_markdown(summary: dict, control_rows: list[dict], target_df: pd.DataFrame) -> str:
    lines = []
    lines.append("# E9-B Route-Leak Review Audit")
    lines.append("")
    lines.append("Scope: audit the narrow route-leak review-preserve rule on the Google-Verizon known-event run.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- run_id: `{summary['run_id']}`")
    lines.append(f"- target_prefix: `{summary['target_prefix']}`")
    lines.append(f"- target_event_count: {summary['target_event_count']}")
    lines.append(f"- target_final_label_counts: `{summary['target_final_label_counts']}`")
    lines.append(f"- route_leak_review_preserved_rows: {summary['route_leak_review_preserved_rows']}")
    lines.append(f"- route_leak_review_preserved_prefixes: {summary['route_leak_review_preserved_prefixes']}")
    lines.append(f"- route_leak_review_preserved_origins: {summary['route_leak_review_preserved_origins']}")
    lines.append(f"- route_leak_review_preserved_target_rows: {summary['route_leak_review_preserved_target_rows']}")
    lines.append(f"- route_leak_review_preserved_final_label_counts: `{summary['route_leak_review_preserved_final_label_counts']}`")
    lines.append("")
    lines.append("## Control Runs")
    lines.append("")
    lines.append("| run_id | route_leak_review_preserved_rows |")
    lines.append("|---|---:|")
    for row in control_rows:
        lines.append(f"| {row['run_id']} | {row['route_leak_review_preserved_rows']} |")
    lines.append("")
    lines.append("## Google Target Rows")
    lines.append("")
    lines.append("| event_id | final_alert_label | augmentation_label | risk_score | certainty_score | conflict_score |")
    lines.append("|---|---|---|---:|---:|---:|")
    if target_df.empty:
        lines.append("| <empty> | | | | | |")
    else:
        for _, row in target_df.iterrows():
            lines.append(
                f"| {row.get('event_id','')} | {row.get('final_alert_label','')} | {row.get('augmentation_label','')} | "
                f"{float(row.get('risk_score', 0.0)):.4f} | {float(row.get('certainty_score', 0.0)):.4f} | {float(row.get('conflict_score', 0.0)):.4f} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit route-leak review preservation on Google-Verizon known-event run.")
    ap.add_argument("--google-run-id", default=DEFAULT_GOOGLE_RUN_ID)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = ap.parse_args()

    base = Path.cwd()
    output_dir = base / args.output_dir
    ensure_dir(output_dir)

    summary, preserved_df = audit_google_run(base, args.google_run_id)
    control_rows = audit_control_runs(base, DEFAULT_CONTROL_RUN_IDS)
    target_df = google_target_rows(base, args.google_run_id)

    preserved_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "risk_score",
        "certainty_score",
        "conflict_score",
        "augmentation_label",
        "route_leak_review_preserved",
    ]
    keep_cols = [c for c in preserved_cols if c in preserved_df.columns]
    preserved_df.loc[:, keep_cols].to_csv(output_dir / "google_preserved_review_rows.csv", index=False, encoding="utf-8-sig")
    target_df.to_csv(output_dir / "google_target_rows.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(control_rows).to_csv(output_dir / "control_runs.csv", index=False, encoding="utf-8-sig")
    (output_dir / "e9b_route_leak_review_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "e9b_route_leak_review_audit.md").write_text(
        build_markdown(summary, control_rows, target_df),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
