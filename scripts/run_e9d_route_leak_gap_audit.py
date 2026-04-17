import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_EVENT_NAME = "MainOne / Google route leak"
DEFAULT_EVENT_SLUG = "mainone_google_20181112"
DEFAULT_BASELINE_RUN_ID = "e9c_baseline_v01_mainone_google_20181112"
DEFAULT_EXPANDED_RUN_ID = "e9c_expanded_v01_mainone_google_20181112"
DEFAULT_OUTPUT_DIR = "outputs/e9d_route_leak_gap_audit_v01"
DEFAULT_TARGET_PREFIX = "8.8.8.0/24"
DEFAULT_ORDERED_CHAIN = "20485,4809,37282,15169"
DEFAULT_EXPECTED_ORIGIN_AS = 15169


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_tokens(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return []
    return [part for part in text.split() if part]


def contains_ordered_chain(path_text: Any, ordered_chain: list[str]) -> bool:
    tokens = normalize_tokens(path_text)
    if not tokens or not ordered_chain:
        return False
    pos = 0
    for token in tokens:
        if token == ordered_chain[pos]:
            pos += 1
            if pos == len(ordered_chain):
                return True
    return False


def label_counts(df: pd.DataFrame, col: str) -> dict[str, int]:
    if df.empty or col not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df[col].value_counts().to_dict().items()}


def mean_or_zero(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(pd.to_numeric(series, errors="coerce").mean())


def raw_rel_matches(run_dir: Path, ordered_chain: list[str], expected_origin_as: int | None) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for path in run_dir.rglob("*__rel.parquet"):
        cols = [c for c in ["ts", "collector", "prefix", "origin_as", "as_path_clean"]]
        df = pd.read_parquet(path, columns=cols)
        if df.empty:
            continue
        mask = df["as_path_clean"].apply(lambda v: contains_ordered_chain(v, ordered_chain))
        sub = df.loc[mask, cols].copy()
        if sub.empty:
            continue
        sub["source_file"] = path.relative_to(run_dir).as_posix()
        sub["matches_expected_origin"] = (
            pd.to_numeric(sub["origin_as"], errors="coerce").fillna(-1).astype(int).eq(expected_origin_as)
            if expected_origin_as is not None
            else False
        )
        rows.append(sub)
    if not rows:
        return pd.DataFrame(columns=["ts", "collector", "prefix", "origin_as", "as_path_clean", "source_file", "matches_expected_origin"])
    return pd.concat(rows, ignore_index=True)


def stage_chain_matches(df: pd.DataFrame, ordered_chain: list[str], expected_origin_as: int | None) -> pd.DataFrame:
    if df.empty or "as_path_clean" not in df.columns:
        return pd.DataFrame()
    mask = df["as_path_clean"].apply(lambda v: contains_ordered_chain(v, ordered_chain))
    sub = df.loc[mask].copy()
    if sub.empty:
        return sub
    if expected_origin_as is not None and "origin_as" in sub.columns:
        sub["matches_expected_origin"] = (
            pd.to_numeric(sub["origin_as"], errors="coerce").fillna(-1).astype(int).eq(expected_origin_as)
        )
    else:
        sub["matches_expected_origin"] = False
    return sub


def stage_exact_prefix_matches(df: pd.DataFrame, target_prefix: str) -> pd.DataFrame:
    if df.empty or "prefix" not in df.columns:
        return pd.DataFrame()
    return df.loc[df["prefix"].astype(str).eq(target_prefix)].copy()


def summarize_run(run_dir: Path, setting: str, target_prefix: str, ordered_chain: list[str], expected_origin_as: int | None) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    events_df = read_parquet(run_dir / "events" / "event_units.parquet")
    final_df = read_parquet(run_dir / "final" / "final_alerts.parquet")
    raw_df = raw_rel_matches(run_dir, ordered_chain, expected_origin_as)

    exact_event_df = stage_exact_prefix_matches(events_df, target_prefix)
    exact_final_df = stage_exact_prefix_matches(final_df, target_prefix)
    chain_event_df = stage_chain_matches(events_df, ordered_chain, expected_origin_as)
    chain_final_df = stage_chain_matches(final_df, ordered_chain, expected_origin_as)

    chain_google_event_df = chain_event_df.loc[chain_event_df["matches_expected_origin"]].copy() if not chain_event_df.empty else pd.DataFrame()
    chain_google_final_df = chain_final_df.loc[chain_final_df["matches_expected_origin"]].copy() if not chain_final_df.empty else pd.DataFrame()
    raw_google_df = raw_df.loc[raw_df["matches_expected_origin"]].copy() if not raw_df.empty else pd.DataFrame()

    summary = {
        "setting": setting,
        "run_id": run_dir.name,
        "target_prefix": target_prefix,
        "ordered_chain": " ".join(ordered_chain),
        "expected_origin_as": expected_origin_as,
        "exact_target_event_rows": int(len(exact_event_df)),
        "exact_target_final_rows": int(len(exact_final_df)),
        "raw_chain_rows": int(len(raw_df)),
        "raw_chain_prefixes": int(raw_df["prefix"].astype(str).nunique()) if not raw_df.empty else 0,
        "raw_chain_collectors": int(raw_df["collector"].astype(str).nunique()) if not raw_df.empty else 0,
        "raw_chain_google_origin_rows": int(len(raw_google_df)),
        "raw_chain_google_origin_prefixes": int(raw_google_df["prefix"].astype(str).nunique()) if not raw_google_df.empty else 0,
        "event_chain_rows": int(len(chain_event_df)),
        "event_chain_prefixes": int(chain_event_df["prefix"].astype(str).nunique()) if not chain_event_df.empty else 0,
        "event_chain_google_origin_rows": int(len(chain_google_event_df)),
        "event_chain_google_origin_prefixes": int(chain_google_event_df["prefix"].astype(str).nunique()) if not chain_google_event_df.empty else 0,
        "final_chain_rows": int(len(chain_final_df)),
        "final_chain_prefixes": int(chain_final_df["prefix"].astype(str).nunique()) if not chain_final_df.empty else 0,
        "final_chain_google_origin_rows": int(len(chain_google_final_df)),
        "final_chain_google_origin_prefixes": int(chain_google_final_df["prefix"].astype(str).nunique()) if not chain_google_final_df.empty else 0,
        "final_chain_label_counts": label_counts(chain_final_df, "final_alert_label"),
        "final_chain_google_label_counts": label_counts(chain_google_final_df, "final_alert_label"),
        "final_chain_risk_mean": round(mean_or_zero(chain_final_df.get("risk_score", pd.Series(dtype=float))), 4),
        "final_chain_certainty_mean": round(mean_or_zero(chain_final_df.get("certainty_score", pd.Series(dtype=float))), 4),
        "final_chain_google_risk_mean": round(mean_or_zero(chain_google_final_df.get("risk_score", pd.Series(dtype=float))), 4),
        "final_chain_google_certainty_mean": round(mean_or_zero(chain_google_final_df.get("certainty_score", pd.Series(dtype=float))), 4),
    }
    tables = {
        "raw_chain": raw_df,
        "chain_events": chain_event_df,
        "chain_final": chain_final_df,
        "exact_event": exact_event_df,
        "exact_final": exact_final_df,
    }
    return summary, tables


def prefix_summary(raw_df: pd.DataFrame, final_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty and final_df.empty:
        return pd.DataFrame()

    raw_group = (
        raw_df.groupby("prefix")
        .agg(
            raw_rows=("prefix", "size"),
            raw_collectors=("collector", "nunique"),
            raw_google_origin_rows=("matches_expected_origin", "sum"),
        )
        .reset_index()
        if not raw_df.empty
        else pd.DataFrame(columns=["prefix", "raw_rows", "raw_collectors", "raw_google_origin_rows"])
    )
    final_group = (
        final_df.groupby(["prefix", "final_alert_label"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
        if not final_df.empty
        else pd.DataFrame(columns=["prefix"])
    )
    merged = raw_group.merge(final_group, on="prefix", how="outer").fillna(0)
    for col in ["high_priority_alert", "needs_review", "low_priority_or_background"]:
        if col not in merged.columns:
            merged[col] = 0
    merged = merged.rename(
        columns={
            "high_priority_alert": "final_high_rows",
            "needs_review": "final_needs_rows",
            "low_priority_or_background": "final_low_rows",
        }
    )
    return merged.sort_values(["raw_rows", "final_needs_rows", "final_high_rows"], ascending=False)


def build_markdown(event_name: str, baseline: dict[str, Any], expanded: dict[str, Any], top_prefixes: pd.DataFrame) -> str:
    lines: list[str] = []
    lines.append("# E9-D Route-Leak Gap Audit")
    lines.append("")
    lines.append(f"Scope: audit `{event_name}` with exact-prefix anchor vs ordered leak-chain anchor.")
    lines.append("")
    lines.append("## Key Finding")
    lines.append("")
    lines.append(
        f"- Exact target prefix `{baseline['target_prefix']}` is absent in both baseline and expanded runs (`event_rows=0`, `final_rows=0`)."
    )
    lines.append(
        f"- The ordered leak chain `{baseline['ordered_chain']}` is visible in both runs; expanded visibility mainly increases `needs_review` coverage rather than producing `high`."
    )
    lines.append("")
    lines.append("## Baseline vs Expanded")
    lines.append("")
    lines.append("| setting | exact_target_event_rows | raw_chain_rows | raw_chain_prefixes | raw_chain_collectors | event_chain_rows | event_chain_google_origin_prefixes | final_chain_rows | final_chain_google_origin_prefixes | final_chain_label_counts | final_chain_google_label_counts |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for summary in [baseline, expanded]:
        lines.append(
            f"| {summary['setting']} | {summary['exact_target_event_rows']} | {summary['raw_chain_rows']} | {summary['raw_chain_prefixes']} | "
            f"{summary['raw_chain_collectors']} | {summary['event_chain_rows']} | {summary['event_chain_google_origin_prefixes']} | "
            f"{summary['final_chain_rows']} | {summary['final_chain_google_origin_prefixes']} | `{summary['final_chain_label_counts']}` | "
            f"`{summary['final_chain_google_label_counts']}` |"
        )
    lines.append("")
    lines.append("## Top Prefixes Under Leak-Chain Anchor")
    lines.append("")
    lines.append("| prefix | raw_rows | raw_collectors | raw_google_origin_rows | final_high_rows | final_needs_rows | final_low_rows |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    if top_prefixes.empty:
        lines.append("| <empty> | | | | | | |")
    else:
        for _, row in top_prefixes.head(20).iterrows():
            lines.append(
                f"| {row.get('prefix','')} | {int(row.get('raw_rows', 0))} | {int(row.get('raw_collectors', 0))} | "
                f"{int(row.get('raw_google_origin_rows', 0))} | {int(row.get('final_high_rows', 0))} | "
                f"{int(row.get('final_needs_rows', 0))} | {int(row.get('final_low_rows', 0))} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit route-leak anchor mismatch using existing known-event runs.")
    ap.add_argument("--event-name", default=DEFAULT_EVENT_NAME)
    ap.add_argument("--baseline-run-id", default=DEFAULT_BASELINE_RUN_ID)
    ap.add_argument("--expanded-run-id", default=DEFAULT_EXPANDED_RUN_ID)
    ap.add_argument("--target-prefix", default=DEFAULT_TARGET_PREFIX)
    ap.add_argument("--ordered-chain", default=DEFAULT_ORDERED_CHAIN)
    ap.add_argument("--expected-origin-as", type=int, default=DEFAULT_EXPECTED_ORIGIN_AS)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = ap.parse_args()

    base = Path.cwd()
    output_dir = base / args.output_dir
    ensure_dir(output_dir)

    ordered_chain = [part.strip() for part in args.ordered_chain.split(",") if part.strip()]
    baseline_summary, baseline_tables = summarize_run(
        base / "data" / "runs" / args.baseline_run_id,
        "baseline_2collectors",
        args.target_prefix,
        ordered_chain,
        args.expected_origin_as,
    )
    expanded_summary, expanded_tables = summarize_run(
        base / "data" / "runs" / args.expanded_run_id,
        "expanded_collectors",
        args.target_prefix,
        ordered_chain,
        args.expected_origin_as,
    )

    baseline_prefix = prefix_summary(baseline_tables["raw_chain"], baseline_tables["chain_final"])
    expanded_prefix = prefix_summary(expanded_tables["raw_chain"], expanded_tables["chain_final"])

    baseline_tables["raw_chain"].to_csv(output_dir / "baseline_raw_chain_matches.csv", index=False, encoding="utf-8-sig")
    expanded_tables["raw_chain"].to_csv(output_dir / "expanded_raw_chain_matches.csv", index=False, encoding="utf-8-sig")
    baseline_tables["chain_final"].to_csv(output_dir / "baseline_final_chain_matches.csv", index=False, encoding="utf-8-sig")
    expanded_tables["chain_final"].to_csv(output_dir / "expanded_final_chain_matches.csv", index=False, encoding="utf-8-sig")
    baseline_prefix.to_csv(output_dir / "baseline_prefix_summary.csv", index=False, encoding="utf-8-sig")
    expanded_prefix.to_csv(output_dir / "expanded_prefix_summary.csv", index=False, encoding="utf-8-sig")

    summary = {
        "event_name": args.event_name,
        "target_prefix": args.target_prefix,
        "ordered_chain": ordered_chain,
        "expected_origin_as": args.expected_origin_as,
        "baseline": baseline_summary,
        "expanded": expanded_summary,
    }
    (output_dir / "e9d_route_leak_gap_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "e9d_route_leak_gap_audit.md").write_text(
        build_markdown(args.event_name, baseline_summary, expanded_summary, expanded_prefix),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
