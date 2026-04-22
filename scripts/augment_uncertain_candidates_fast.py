import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_RUN_ID = "20260313T032554_4f9be28c"
UNCERTAIN_LABEL = "suspicious_but_uncertain"

STRUCTURAL_REASONS = {
    "unseen_origin_for_prefix",
    "unseen_path_for_prefix_origin",
    "unseen_exact_path",
    "weak_path_history",
    "abnormal_path_length_for_prefix_origin",
    "cross_collector_prefix_origin_burst",
}

WEAK_REASONS = {
    "unusually_short_duration_for_prefix",
    "unusually_low_visibility_for_prefix",
    "unusually_low_visibility_for_prefix_origin",
    "sparse_short_lived_event",
}

AUGMENT_WEIGHTS = {
    "multi_view_support_score": 0.35,
    "historical_deviation_support_score": 0.40,
    "consistency_recheck_score": 0.25,
}

AUGMENT_CONFIG = {
    "related_window_sec": 300,
    "promoted_threshold": 65.0,
    "demoted_threshold": 35.0,
    "block_missing_promotion": False,
    "route_leak_review_prefix_min": 5000.0,
    "route_leak_review_evidence_min": 30.0,
    "route_leak_review_conflict_max": 10.0,
    "route_leak_review_certainty_min": 20.0,
}

AUGMENT_PROFILES = {
    "default": {},
    "modern_missing_block": {
        "block_missing_promotion": True,
    },
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


def parse_collector_set(value) -> set[str]:
    if value is None or pd.isna(value):
        return set()
    text = str(value).strip()
    if not text:
        return set()
    return {x.strip() for x in text.split("|") if x.strip()}


def safe_num(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def clip_0_100(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def ensure_gating_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "event_id": "",
        "run_id": "",
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "risk_score": 0.0,
        "gating_label": "",
        "certainty_score": 0.0,
        "conflict_score": 0.0,
        "structural_novelty_score": 0.0,
        "weak_signal_score": 0.0,
        "history_rarity_score": 0.0,
        "path_consistency_score": 0.0,
        "top_contributing_factor": "",
        "matched_rule_count": 0.0,
        "missing_origin_or_path": False,
        "candidate_reasons": "[]",
        "path_seen_before": False,
        "promoted_from_low": False,
        "origin_burst_event_count": 0.0,
        "origin_burst_prefix_count": 0.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    text_cols = ["event_id", "run_id", "prefix", "as_path_clean", "gating_label", "top_contributing_factor", "candidate_reasons"]
    for col in text_cols:
        out[col] = out[col].fillna("").astype(str)

    numeric_cols = [
        "risk_score",
        "certainty_score",
        "conflict_score",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "matched_rule_count",
        "origin_burst_event_count",
        "origin_burst_prefix_count",
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    if out["missing_origin_or_path"].dtype != bool:
        out["missing_origin_or_path"] = out["missing_origin_or_path"].fillna(False).astype(bool)
    if out["path_seen_before"].dtype != bool:
        out["path_seen_before"] = out["path_seen_before"].fillna(False).astype(bool)
    if out["promoted_from_low"].dtype != bool:
        out["promoted_from_low"] = out["promoted_from_low"].fillna(False).astype(bool)
    return out


def ensure_event_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "event_id": "",
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "first_seen": 0.0,
        "last_seen": 0.0,
        "collector_set": "",
        "collector_count": 0.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    out["event_id"] = out["event_id"].fillna("").astype(str)
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["collector_set"] = out["collector_set"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    out["first_seen"] = pd.to_numeric(out["first_seen"], errors="coerce").fillna(0.0)
    out["last_seen"] = pd.to_numeric(out["last_seen"], errors="coerce").fillna(0.0)
    out["collector_count"] = pd.to_numeric(out["collector_count"], errors="coerce").fillna(0.0)
    out = out[out["event_id"] != ""].copy()
    return out


def ensure_baseline_prefix(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "prefix" not in out.columns:
        out["prefix"] = ""
    if "total_events" not in out.columns:
        out["total_events"] = 0.0
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
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    out["total_events"] = pd.to_numeric(out["total_events"], errors="coerce").fillna(0.0)
    out["unique_paths"] = pd.to_numeric(out["unique_paths"], errors="coerce").fillna(0.0)
    return out


def ensure_baseline_path(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {"prefix": "", "origin_as": None, "as_path_clean": "", "total_events": 0.0}
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["total_events"] = pd.to_numeric(out["total_events"], errors="coerce").fillna(0.0)
    return out


def calc_multi_view_support_score(
    row: pd.Series,
    event_row: pd.Series,
    prefix_events: pd.DataFrame,
    po_events: pd.DataFrame,
    path_events: pd.DataFrame,
) -> tuple[float, dict]:
    own_collectors = parse_collector_set(event_row.get("collector_set", ""))
    own_count = int(safe_num(event_row.get("collector_count"), len(own_collectors)))
    if own_count <= 0:
        own_count = len(own_collectors)

    base = 0.0
    if own_count >= 3:
        base += 40.0
    elif own_count == 2:
        base += 26.0
    elif own_count == 1:
        base += 12.0

    related_window = safe_num(AUGMENT_CONFIG["related_window_sec"], 300.0)
    current_start = safe_num(event_row.get("first_seen"), 0.0)
    current_end = safe_num(event_row.get("last_seen"), current_start)
    left = current_start - related_window
    right = current_end + related_window

    def near_time(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        mask = (df["first_seen"] <= right) & (df["last_seen"] >= left)
        out = df[mask]
        return out[out["event_id"] != row["event_id"]]

    near_prefix = near_time(prefix_events)
    near_po = near_time(po_events)
    near_path = near_time(path_events)

    prefix_collector_union = set()
    for value in near_prefix["collector_set"].tolist():
        prefix_collector_union.update(parse_collector_set(value))
    extra_collectors = prefix_collector_union - own_collectors

    if len(extra_collectors) >= 2:
        base += 30.0
    elif len(extra_collectors) == 1:
        base += 16.0

    if len(near_po) >= 2:
        base += 15.0
    elif len(near_po) == 1:
        base += 8.0

    if len(near_path) >= 1:
        base += 15.0

    isolated = near_prefix.empty and near_po.empty and near_path.empty
    if isolated:
        base -= 20.0

    detail = {
        "own_collector_count": own_count,
        "extra_collectors_near_prefix": sorted(extra_collectors),
        "near_prefix_event_count": int(len(near_prefix)),
        "near_prefix_origin_event_count": int(len(near_po)),
        "near_exact_path_event_count": int(len(near_path)),
        "isolated": isolated,
    }
    return clip_0_100(base), detail


def build_fast_event_context(events_df: pd.DataFrame) -> dict:
    """Build array-backed event indexes to avoid per-row DataFrame slicing."""
    event_ids = events_df["event_id"].astype(str).to_numpy()
    first_seen = events_df["first_seen"].to_numpy()
    last_seen = events_df["last_seen"].to_numpy()
    collector_sets = events_df["collector_set"].astype(str).to_numpy()
    collector_counts = events_df["collector_count"].to_numpy()
    prefix_index = events_df.groupby("prefix", sort=False).indices
    po_index = events_df.groupby(["prefix", "origin_as_num"], dropna=False, sort=False).indices
    path_index = events_df.groupby(["prefix", "origin_as_num", "as_path_clean"], dropna=False, sort=False).indices

    def build_interval_index(index: dict) -> dict:
        out = {}
        for key, positions in index.items():
            positions = np.asarray(positions, dtype=np.int64)
            first_order = positions[np.argsort(first_seen[positions], kind="mergesort")]
            last_order = positions[np.argsort(last_seen[positions], kind="mergesort")]
            out[key] = {
                "first_positions": first_order,
                "first_values": first_seen[first_order],
                "last_positions": last_order,
                "last_values": last_seen[last_order],
                "size": int(len(positions)),
            }
        return out

    return {
        "event_ids": event_ids,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "collector_sets": collector_sets,
        "collector_counts": collector_counts,
        "prefix_interval_index": build_interval_index(prefix_index),
        "po_interval_index": build_interval_index(po_index),
        "path_interval_index": build_interval_index(path_index),
        "event_row_pos": {event_id: idx for idx, event_id in enumerate(event_ids.tolist())},
        "collector_cache": {},
    }


def parse_collector_set_cached(value, cache: dict) -> set[str]:
    key = "" if value is None or pd.isna(value) else str(value)
    cached = cache.get(key)
    if cached is not None:
        return cached
    parsed = parse_collector_set(key)
    cache[key] = parsed
    return parsed


def calc_multi_view_support_score_fast(row: dict, ctx: dict) -> tuple[float, dict]:
    """Equivalent multi-view score using array indexes instead of DataFrame take/filter."""
    event_id = str(row.get("event_id", ""))
    event_idx = ctx["event_row_pos"].get(event_id)
    collector_cache = ctx["collector_cache"]

    if event_idx is None:
        own_collectors = parse_collector_set_cached(row.get("event_collector_set", ""), collector_cache)
        own_count = int(safe_num(row.get("event_collector_count"), len(own_collectors)))
        current_start = safe_num(row.get("first_seen"), 0.0)
        current_end = safe_num(row.get("last_seen"), current_start)
    else:
        own_collectors = parse_collector_set_cached(ctx["collector_sets"][event_idx], collector_cache)
        own_count = int(safe_num(ctx["collector_counts"][event_idx], len(own_collectors)))
        current_start = safe_num(ctx["first_seen"][event_idx], 0.0)
        current_end = safe_num(ctx["last_seen"][event_idx], current_start)

    if own_count <= 0:
        own_count = len(own_collectors)

    base = 0.0
    if own_count >= 3:
        base += 40.0
    elif own_count == 2:
        base += 26.0
    elif own_count == 1:
        base += 12.0

    related_window = safe_num(AUGMENT_CONFIG["related_window_sec"], 300.0)
    left = current_start - related_window
    right = current_end + related_window

    prefix = str(row.get("prefix", ""))
    origin = row.get("origin_as_num", float("nan"))
    path = str(row.get("as_path_clean", ""))

    def interval_count(index_name: str, key) -> int:
        data = ctx[index_name].get(key)
        if data is None:
            return 0
        hi_first = int(np.searchsorted(data["first_values"], right, side="right"))
        lo_last = int(np.searchsorted(data["last_values"], left, side="left"))
        count = hi_first - lo_last
        if event_idx is not None:
            count -= 1
        return max(0, int(count))

    def near_prefix_stats(key) -> tuple[int, set[str]]:
        data = ctx["prefix_interval_index"].get(key)
        if data is None:
            return 0, set()
        count = 0
        collector_union = set()
        hi_first = int(np.searchsorted(data["first_values"], right, side="right"))
        lo_last = int(np.searchsorted(data["last_values"], left, side="left"))
        first_candidates = data["first_positions"][:hi_first]
        last_candidates = data["last_positions"][lo_last:]
        positions = first_candidates if len(first_candidates) <= len(last_candidates) else last_candidates
        first_seen = ctx["first_seen"]
        last_seen = ctx["last_seen"]
        event_ids = ctx["event_ids"]
        collector_sets = ctx["collector_sets"]
        for pos in positions:
            if first_seen[pos] <= right and last_seen[pos] >= left and event_ids[pos] != event_id:
                count += 1
                collector_union.update(parse_collector_set_cached(collector_sets[pos], collector_cache))
        return count, collector_union

    near_prefix_count, prefix_collector_union = near_prefix_stats(prefix)
    near_po_count = interval_count("po_interval_index", (prefix, origin))
    near_path_count = interval_count("path_interval_index", (prefix, origin, path))

    extra_collectors = prefix_collector_union - own_collectors

    if len(extra_collectors) >= 2:
        base += 30.0
    elif len(extra_collectors) == 1:
        base += 16.0

    if near_po_count >= 2:
        base += 15.0
    elif near_po_count == 1:
        base += 8.0

    if near_path_count >= 1:
        base += 15.0

    isolated = near_prefix_count == 0 and near_po_count == 0 and near_path_count == 0
    if isolated:
        base -= 20.0

    detail = {
        "own_collector_count": own_count,
        "extra_collectors_near_prefix": sorted(extra_collectors),
        "near_prefix_event_count": int(near_prefix_count),
        "near_prefix_origin_event_count": int(near_po_count),
        "near_exact_path_event_count": int(near_path_count),
        "isolated": isolated,
    }
    return clip_0_100(base), detail


def rarity_support(count: float, low1: float, low2: float, low3: float) -> float:
    c = safe_num(count, 0.0)
    if c <= low1:
        return 1.0
    if c <= low2:
        return 0.7
    if c <= low3:
        return 0.4
    return 0.15


def calc_historical_deviation_support_score(row: pd.Series, reasons: list[str]) -> tuple[float, dict]:
    structural_hits = [r for r in reasons if r in STRUCTURAL_REASONS]
    weak_hits = [r for r in reasons if r in WEAK_REASONS]

    score = 0.0
    if "unseen_origin_for_prefix" in structural_hits:
        score += 22.0
    if "unseen_path_for_prefix_origin" in structural_hits:
        score += 20.0
    if "unseen_exact_path" in structural_hits:
        score += 18.0
    if "abnormal_path_length_for_prefix_origin" in structural_hits:
        score += 15.0
    if "weak_path_history" in structural_hits:
        score += 12.0

    risk_score = safe_num(row.get("risk_score"))
    certainty = safe_num(row.get("certainty_score"))
    conflict = safe_num(row.get("conflict_score"))
    structural = safe_num(row.get("structural_novelty_score"))

    if risk_score >= 50.0:
        score += 12.0
    elif risk_score >= 40.0:
        score += 6.0

    if certainty >= 55.0:
        score += 8.0
    elif certainty < 30.0:
        score -= 6.0

    if conflict >= 45.0:
        score -= 12.0

    prefix_total = safe_num(row.get("prefix_total_events"), 0.0)
    po_total = safe_num(row.get("po_total_events"), 0.0)
    path_total = safe_num(row.get("path_total_events"), 0.0)
    path_seen = bool(row.get("path_seen_before", False))

    score += 12.0 * rarity_support(prefix_total, 2, 5, 20)
    score += 14.0 * rarity_support(po_total, 2, 5, 20)
    if not path_seen:
        score += 12.0
    else:
        score += 12.0 * rarity_support(path_total, 1, 3, 10)

    if not structural_hits and len(weak_hits) >= 2:
        score -= 18.0
    if structural < 20.0 and len(structural_hits) == 0:
        score -= 10.0

    detail = {
        "structural_reason_count": len(structural_hits),
        "weak_reason_count": len(weak_hits),
        "prefix_total_events": prefix_total,
        "po_total_events": po_total,
        "path_total_events": path_total,
        "path_seen_before": path_seen,
    }
    return clip_0_100(score), detail


def calc_consistency_recheck_score(row: pd.Series, reasons: list[str]) -> tuple[float, dict]:
    structural = safe_num(row.get("structural_novelty_score"))
    weak = safe_num(row.get("weak_signal_score"))
    path_consistency = safe_num(row.get("path_consistency_score"))
    matched = safe_num(row.get("matched_rule_count"))
    certainty = safe_num(row.get("certainty_score"))
    conflict = safe_num(row.get("conflict_score"))
    missing = bool(row.get("missing_origin_or_path", False))

    structural_hits = [r for r in reasons if r in STRUCTURAL_REASONS]
    weak_hits = [r for r in reasons if r in WEAK_REASONS]

    score = 30.0
    if structural >= 40.0:
        score += 20.0
    if structural >= weak + 10.0:
        score += 12.0
    if weak >= 55.0 and structural < 25.0:
        score -= 15.0

    if path_consistency >= 50.0:
        score += 15.0
    elif path_consistency < 20.0:
        score -= 15.0

    if matched >= 3:
        score += 10.0
    elif matched <= 1:
        score -= 6.0

    if len(structural_hits) >= 2 and len(weak_hits) >= 1:
        score += 10.0
    if len(structural_hits) == 0 and len(weak_hits) >= 2:
        score -= 12.0

    if certainty >= 60.0:
        score += 8.0
    elif certainty < 25.0:
        score -= 8.0

    if conflict >= 45.0:
        score -= 15.0
    elif conflict <= 10.0:
        score += 5.0

    if missing:
        score -= 20.0

    detail = {
        "structural_reason_count": len(structural_hits),
        "weak_reason_count": len(weak_hits),
        "matched_rule_count": matched,
        "missing_origin_or_path": missing,
    }
    return clip_0_100(score), detail


def build_augment_config(profile: str) -> dict:
    if profile not in AUGMENT_PROFILES:
        raise SystemExit(f"unknown augment profile: {profile}")
    out = dict(AUGMENT_CONFIG)
    out.update(AUGMENT_PROFILES[profile])
    return out


def choose_augmentation_outcome(
    evidence_support_score: float,
    *,
    missing_origin_or_path: bool,
    config: dict,
) -> tuple[str, bool]:
    if evidence_support_score >= config["promoted_threshold"]:
        if config.get("block_missing_promotion", False) and missing_origin_or_path:
            return "retained_uncertain", True
        return "promoted_suspicious", False
    if evidence_support_score < config["demoted_threshold"]:
        return "demoted_suspicious", False
    return "retained_uncertain", False


def should_preserve_route_leak_review(row: pd.Series, reasons: list[str], evidence_support_score: float) -> bool:
    if str(row.get("gating_label", "")) != UNCERTAIN_LABEL:
        return False
    if evidence_support_score >= AUGMENT_CONFIG["demoted_threshold"]:
        return False
    if evidence_support_score < AUGMENT_CONFIG["route_leak_review_evidence_min"]:
        return False
    if not bool(row.get("promoted_from_low", False)):
        return False
    if "cross_collector_prefix_origin_burst" not in reasons:
        return False
    if "single_collector_visibility" not in reasons:
        return False
    if safe_num(row.get("origin_burst_prefix_count"), 0.0) < AUGMENT_CONFIG["route_leak_review_prefix_min"]:
        return False
    if safe_num(row.get("certainty_score"), 0.0) < AUGMENT_CONFIG["route_leak_review_certainty_min"]:
        return False
    if safe_num(row.get("conflict_score"), 0.0) > AUGMENT_CONFIG["route_leak_review_conflict_max"]:
        return False
    return True


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
        "gating_label",
        "evidence_support_score",
        "augmentation_label",
        "augmentation_explanation",
    ]
    for row in df.head(n)[cols].to_dict("records"):
        print("  - " + json.dumps(row, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Lightweight evidence augmentation for uncertain gated samples.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--gating", default=None, help="Path to gated_candidates.parquet.")
    ap.add_argument("--events", default=None, help="Path to event_units.parquet.")
    ap.add_argument("--baseline-prefix", default=None, help="Path to baseline_prefix.parquet.")
    ap.add_argument("--baseline-prefix-origin", default=None, help="Path to baseline_prefix_origin.parquet.")
    ap.add_argument("--baseline-path", default=None, help="Path to baseline_path.parquet.")
    ap.add_argument(
        "--profile",
        default="default",
        choices=sorted(AUGMENT_PROFILES.keys()),
        help="Augment profile. default preserves historical behavior; modern_missing_block blocks HIGH promotion when missing_origin_or_path=true.",
    )
    ap.add_argument("--output-dir", default=None, help="Output augmentation directory.")
    ap.add_argument("--overwrite", type=str2bool, default=False, help="Overwrite existing outputs.")
    args = ap.parse_args()
    active_config = build_augment_config(args.profile)

    if args.gating:
        gating_path = Path(args.gating)
        run_id = args.run_id or infer_run_id(gating_path) or DEFAULT_RUN_ID
    else:
        run_id = args.run_id or DEFAULT_RUN_ID
        gating_path = Path("data") / "runs" / run_id / "gating" / "gated_candidates.parquet"
    if not gating_path.exists():
        raise SystemExit(f"gating file not found: {gating_path}")

    events_path = Path(args.events) if args.events else Path("data") / "runs" / run_id / "events" / "event_units.parquet"
    baseline_prefix_path = (
        Path(args.baseline_prefix) if args.baseline_prefix else Path("data") / "runs" / run_id / "baseline" / "baseline_prefix.parquet"
    )
    baseline_po_path = (
        Path(args.baseline_prefix_origin)
        if args.baseline_prefix_origin
        else Path("data") / "runs" / run_id / "baseline" / "baseline_prefix_origin.parquet"
    )
    baseline_path_path = (
        Path(args.baseline_path) if args.baseline_path else Path("data") / "runs" / run_id / "baseline" / "baseline_path.parquet"
    )

    for p in [events_path, baseline_prefix_path, baseline_po_path, baseline_path_path]:
        if not p.exists():
            raise SystemExit(f"required input file not found: {p}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "augmentation"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_aug = output_dir / "augmented_candidates.parquet"
    out_summary = output_dir / "augmentation_summary.json"
    if not args.overwrite:
        exists = [p for p in [out_aug, out_summary] if p.exists()]
        if exists:
            raise SystemExit("Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists))

    gating_df = ensure_gating_columns(pd.read_parquet(gating_path))
    uncertain_df = gating_df[gating_df["gating_label"] == UNCERTAIN_LABEL].copy()

    event_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "first_seen",
        "last_seen",
        "collector_set",
        "collector_count",
    ]
    events_df = ensure_event_columns(pd.read_parquet(events_path, columns=event_cols))
    baseline_prefix_df = ensure_baseline_prefix(pd.read_parquet(baseline_prefix_path))
    baseline_po_df = ensure_baseline_prefix_origin(pd.read_parquet(baseline_po_path))
    baseline_path_df = ensure_baseline_path(pd.read_parquet(baseline_path_path))

    uncertain_df = uncertain_df.merge(
        events_df[
            ["event_id", "first_seen", "last_seen", "collector_set", "collector_count"]
        ].rename(
            columns={
                "collector_set": "event_collector_set",
                "collector_count": "event_collector_count",
            }
        ),
        on="event_id",
        how="left",
    )

    uncertain_df = uncertain_df.merge(
        baseline_prefix_df[["prefix", "total_events"]].rename(columns={"total_events": "prefix_total_events"}),
        on="prefix",
        how="left",
    )
    uncertain_df = uncertain_df.merge(
        baseline_po_df[["prefix", "origin_as_num", "total_events", "unique_paths"]].rename(
            columns={"total_events": "po_total_events", "unique_paths": "po_unique_paths"}
        ),
        on=["prefix", "origin_as_num"],
        how="left",
    )
    uncertain_df = uncertain_df.merge(
        baseline_path_df[["prefix", "origin_as_num", "as_path_clean", "total_events"]].rename(
            columns={"total_events": "path_total_events"}
        ),
        on=["prefix", "origin_as_num", "as_path_clean"],
        how="left",
    )
    uncertain_df["path_seen_before"] = uncertain_df["path_total_events"].fillna(0) > 0

    # Keep augmentation scalable for multi-collector experiments: use
    # array-backed indexes instead of materializing DataFrame slices per row.
    relevant_prefixes = set(uncertain_df["prefix"].dropna().astype(str).unique())
    events_df = events_df[events_df["prefix"].isin(relevant_prefixes)].reset_index(drop=True)
    fast_event_context = build_fast_event_context(events_df)

    results = []
    for row in uncertain_df.itertuples(index=False):
        row_s = row._asdict()
        event_id = str(row_s.get("event_id", ""))
        reasons = parse_reason_list(row_s.get("candidate_reasons", "[]"))

        multi_score, multi_detail = calc_multi_view_support_score_fast(row_s, fast_event_context)
        hist_score, hist_detail = calc_historical_deviation_support_score(row_s, reasons)
        cons_score, cons_detail = calc_consistency_recheck_score(row_s, reasons)

        evidence = (
            AUGMENT_WEIGHTS["multi_view_support_score"] * multi_score
            + AUGMENT_WEIGHTS["historical_deviation_support_score"] * hist_score
            + AUGMENT_WEIGHTS["consistency_recheck_score"] * cons_score
        )
        evidence = round(clip_0_100(evidence), 4)
        aug_label, blocked_missing_promotion = choose_augmentation_outcome(
            evidence,
            missing_origin_or_path=bool(row_s.get("missing_origin_or_path", False)),
            config=active_config,
        )
        route_leak_review_preserved = False
        if aug_label == "demoted_suspicious" and should_preserve_route_leak_review(row_s, reasons, evidence):
            aug_label = "retained_uncertain"
            route_leak_review_preserved = True

        explanation = {
            "multi_view_support_detail": multi_detail,
            "historical_deviation_detail": hist_detail,
            "consistency_recheck_detail": cons_detail,
            "weights": AUGMENT_WEIGHTS,
            "reasons": reasons,
            "blocked_missing_promotion": bool(blocked_missing_promotion),
            "profile": args.profile,
            "route_leak_review_preserved": route_leak_review_preserved,
        }

        results.append(
            {
                "event_id": event_id,
                "run_id": str(row_s.get("run_id", run_id)),
                "prefix": str(row_s.get("prefix", "")),
                "origin_as": row_s.get("origin_as"),
                "as_path_clean": str(row_s.get("as_path_clean", "")),
                "risk_score": safe_num(row_s.get("risk_score")),
                "gating_label": str(row_s.get("gating_label", "")),
                "certainty_score": safe_num(row_s.get("certainty_score")),
                "conflict_score": safe_num(row_s.get("conflict_score")),
                "evidence_support_score": evidence,
                "multi_view_support_score": round(multi_score, 4),
                "historical_deviation_support_score": round(hist_score, 4),
                "consistency_recheck_score": round(cons_score, 4),
                "augmentation_label": aug_label,
                "augmentation_explanation": json.dumps(explanation, ensure_ascii=False),
                "promoted_from_uncertain": bool(aug_label == "promoted_suspicious"),
                "demoted_from_uncertain": bool(aug_label == "demoted_suspicious"),
                "blocked_missing_promotion": bool(blocked_missing_promotion),
                "route_leak_review_preserved": route_leak_review_preserved,
            }
        )

    out_df = pd.DataFrame(results)
    if out_df.empty:
        out_df = pd.DataFrame(
            columns=[
                "event_id",
                "run_id",
                "prefix",
                "origin_as",
                "as_path_clean",
                "risk_score",
                "gating_label",
                "certainty_score",
                "conflict_score",
                "evidence_support_score",
                "multi_view_support_score",
                "historical_deviation_support_score",
                "consistency_recheck_score",
                "augmentation_label",
                "augmentation_explanation",
                "promoted_from_uncertain",
                "demoted_from_uncertain",
                "blocked_missing_promotion",
                "route_leak_review_preserved",
            ]
        )

    out_df.to_parquet(out_aug, index=False)

    label_counts = out_df["augmentation_label"].value_counts().to_dict() if not out_df.empty else {}
    promoted = int(label_counts.get("promoted_suspicious", 0))
    retained = int(label_counts.get("retained_uncertain", 0))
    demoted = int(label_counts.get("demoted_suspicious", 0))
    blocked_missing_promotion_count = (
        int(out_df["blocked_missing_promotion"].fillna(False).astype(bool).sum())
        if "blocked_missing_promotion" in out_df.columns
        else 0
    )
    avg_evidence = float(out_df["evidence_support_score"].mean()) if not out_df.empty else 0.0

    summary = {
        "run_id": run_id,
        "profile": args.profile,
        "gating_path": to_rel_path(gating_path),
        "events_path": to_rel_path(events_path),
        "baseline_prefix_path": to_rel_path(baseline_prefix_path),
        "baseline_prefix_origin_path": to_rel_path(baseline_po_path),
        "baseline_path_path": to_rel_path(baseline_path_path),
        "output_augmented_path": to_rel_path(out_aug),
        "output_summary_path": to_rel_path(out_summary),
        "input_uncertain_rows": int(len(uncertain_df)),
        "output_rows": int(len(out_df)),
        "promoted_suspicious_count": promoted,
        "retained_uncertain_count": retained,
        "demoted_suspicious_count": demoted,
        "blocked_missing_promotion_count": blocked_missing_promotion_count,
        "avg_evidence_support_score": avg_evidence,
        "augment_weights": AUGMENT_WEIGHTS,
        "augment_config": active_config,
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_uncertain_rows: {len(uncertain_df)}")
    print(f"profile: {args.profile}")
    print(f"promoted_suspicious: {promoted}")
    print(f"retained_uncertain: {retained}")
    print(f"demoted_suspicious: {demoted}")
    print(f"blocked_missing_promotion: {blocked_missing_promotion_count}")
    print(f"avg_evidence_support_score: {avg_evidence:.4f}")
    print(f"output_augmented_path: {to_rel_path(out_aug)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")

    print_samples(out_df[out_df["augmentation_label"] == "promoted_suspicious"], "promoted_suspicious_samples", 10)
    print_samples(out_df[out_df["augmentation_label"] == "retained_uncertain"], "retained_uncertain_samples", 10)
    print_samples(out_df[out_df["augmentation_label"] == "demoted_suspicious"], "demoted_suspicious_samples", 10)


if __name__ == "__main__":
    main()
