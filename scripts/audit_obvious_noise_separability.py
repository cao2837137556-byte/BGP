"""Audit obvious-noise separability before foreground extraction.

R-NOISE-0 is a read-only audit over candidate-entry rows. It asks whether
operationally obvious background noise can be separated from multi-attack
must-keep weak signals. The script simulates counterfactual suppression
policies, but it does not delete rows, train learning, change the legacy
pipeline, or create attack/benign truth labels.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


MISSING = "missing"

OUTPUT_FILES = [
    "r_noise_0_summary.json",
    "noise_feature_availability.csv",
    "multi_attack_must_keep_coverage.csv",
    "counterfactual_suppression_policy_audit.csv",
    "clean_window_noise_profile.csv",
    "legacy_signal_reference_audit.csv",
    "poisoning_evasion_retention_audit.csv",
    "must_keep_foreground_audit.csv",
    "may_suppress_background_audit.csv",
    "gray_zone_retained_audit.csv",
    "noise_separability_report.md",
]

LOW_SPECIFICITY_TOKENS = [
    "single_collector_visibility",
    "unusually_short_duration_for_prefix",
    "unusually_low_visibility_for_prefix",
    "sparse_short_lived_event",
]
ORIGIN_TOKENS = [
    "new_origin",
    "origin_change",
    "unseen_origin",
    "unseen_origin_for_prefix",
    "unseen_prefix_origin",
    "prefix_origin_not_in_history",
]
PATH_TOKENS = ["unseen_path", "unseen_exact_path", "path_change", "path_manipulation"]
PATH_LENGTH_TOKENS = ["abnormal_path_length", "path_len"]
ROUTE_LEAK_TOKENS = ["route_leak", "leak", "valley", "triplet", "asrel", "as-rel", "path_relation"]
COMMUNITY_TOKENS = ["community", "no_export", "no-advertise", "no_advertise", "nopeer"]
POISONING_TOKENS = ["poison", "poisoning", "evasion", "crafted", "monitor_inconsistency", "history_poisoning"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit obvious-noise separability and suppression safety.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--events", default=None)
    parser.add_argument("--scores", default=None)
    parser.add_argument("--final", default=None)
    parser.add_argument("--rpki", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--sample-size", type=int, default=10000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def run_root(run_id: str) -> Path:
    return Path("data") / "runs" / run_id


def resolve_input(explicit: str | None, default_path: Path | None, required: bool = False) -> Path | None:
    path = Path(explicit) if explicit else default_path
    if path is None:
        if required:
            raise FileNotFoundError("required input path is not configured")
        return None
    if not path.exists():
        if required:
            raise FileNotFoundError(f"required input not found: {path}")
        return None
    return path


def resolve_paths(args: argparse.Namespace) -> dict[str, Path | None]:
    root = run_root(args.run_id)
    return {
        "candidates": resolve_input(args.candidates, root / "candidates" / "candidate_events.parquet", required=True),
        "events": resolve_input(args.events, root / "events" / "event_units.parquet"),
        "scores": resolve_input(args.scores, root / "scores" / "scored_candidates.parquet"),
        "final": resolve_input(args.final, root / "final" / "final_alerts.parquet"),
        "rpki": resolve_input(args.rpki, Path("data") / "evidence" / "rpki" / "vrp_2024-04-16.parquet"),
        "r_agg_3_summary": resolve_input(None, Path("outputs") / "r_agg_3" / args.run_id / "r_agg_3_summary.json"),
        "r_evid_0_summary": resolve_input(None, Path("outputs") / "r_evid_0" / args.run_id / "r_evid_0_summary.json"),
    }


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [output_dir / name for name in OUTPUT_FILES if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(path) for path in existing)
        )


def parquet_info(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or path.suffix.lower() != ".parquet":
        return {"exists": bool(path and path.exists()), "rows": None, "columns": []}
    pf = pq.ParquetFile(path)
    return {"exists": True, "rows": int(pf.metadata.num_rows), "columns": list(pf.schema.names)}


def safe_rate(count: int | float, denominator: int | float) -> float:
    return round(float(count) / float(denominator), 6) if denominator else 0.0


def normalize_text(series: pd.Series) -> pd.Series:
    return series.fillna(MISSING).astype(str)


def lower_text(series: pd.Series) -> pd.Series:
    return normalize_text(series).str.lower()


def contains_any(series: pd.Series, tokens: list[str]) -> pd.Series:
    text = lower_text(series)
    result = pd.Series(False, index=series.index)
    for token in tokens:
        result = result | text.str.contains(token, regex=False)
    return result


def non_missing_rate(series: pd.Series) -> float:
    text = lower_text(series)
    missing = text.isin(["", MISSING, "none", "nan", "[]"])
    return safe_rate(int((~missing).sum()), len(series))


def bool_series(series: pd.Series, default: bool = False) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(default)
    text = lower_text(series)
    truthy = text.isin(["true", "1", "yes"])
    falsy = text.isin(["false", "0", "no"])
    return truthy.where(truthy | falsy, default)


def numeric_series(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def normalize_asn(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def make_prefix_origin_key(prefix: Any, origin: Any) -> str:
    prefix_text = str(prefix).strip() if prefix is not None else MISSING
    asn = normalize_asn(origin)
    if not prefix_text or prefix_text.lower() in {MISSING, "none", "nan"} or asn is None:
        return MISSING
    return f"{prefix_text}|{asn}"


def load_candidates(path: Path) -> pd.DataFrame:
    wanted = [
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
        "candidate_flag",
        "candidate_reasons",
        "matched_rule_count",
        "prefix_total_events",
        "prefix_unique_origins",
        "po_total_events",
        "po_unique_paths",
        "po_collector_support",
        "po_time_span_sec",
        "path_total_events",
        "path_seen_before",
    ]
    schema_names = set(pq.ParquetFile(path).schema.names)
    columns = [column for column in wanted if column in schema_names]
    df = pd.read_parquet(path, columns=columns, engine="pyarrow")
    for column in wanted:
        if column not in df.columns:
            df[column] = MISSING
    df["prefix_origin_key"] = [
        make_prefix_origin_key(prefix, origin)
        for prefix, origin in zip(df["prefix"], df["origin_as"])
    ]
    return df


def attach_event_fields(df: pd.DataFrame, events_path: Path | None) -> dict[str, Any]:
    df["event_joined"] = False
    df["first_seen"] = MISSING
    df["last_seen"] = MISSING
    df["collector"] = MISSING
    df["rel_unknown_cnt"] = 0
    df["rel_has_unknown"] = False
    df["rel_seq"] = MISSING
    if events_path is None or not events_path.exists():
        return {"events_present": False, "event_join_rate": 0.0, "rel_fields_present": False}
    schema_names = set(pq.ParquetFile(events_path).schema.names)
    needed = [
        column
        for column in ["event_id", "first_seen", "last_seen", "collector", "rel_unknown_cnt", "rel_has_unknown", "rel_seq"]
        if column in schema_names
    ]
    if "event_id" not in needed:
        return {"events_present": True, "event_join_rate": 0.0, "rel_fields_present": False}
    events = pd.read_parquet(events_path, columns=needed, engine="pyarrow").drop_duplicates("event_id")
    events = events.set_index("event_id")
    joined = df["event_id"].isin(events.index)
    df["event_joined"] = joined
    for column in ["first_seen", "last_seen", "collector", "rel_seq"]:
        if column in events.columns:
            df[column] = df["event_id"].map(events[column]).fillna(MISSING)
    if "rel_unknown_cnt" in events.columns:
        df["rel_unknown_cnt"] = df["event_id"].map(events["rel_unknown_cnt"]).fillna(0)
    if "rel_has_unknown" in events.columns:
        df["rel_has_unknown"] = df["event_id"].map(events["rel_has_unknown"]).fillna(False).astype(bool)
    return {
        "events_present": True,
        "event_join_rate": safe_rate(int(joined.sum()), len(df)),
        "rel_fields_present": any(column in events.columns for column in ["rel_unknown_cnt", "rel_has_unknown", "rel_seq"]),
    }


def attach_legacy_final_reference(df: pd.DataFrame, final_path: Path | None) -> dict[str, Any]:
    for column in [
        "legacy_final_alert_label",
        "legacy_risk_bucket",
        "legacy_gating_label",
        "legacy_augmentation_label",
    ]:
        df[column] = MISSING
    if final_path is None or not final_path.exists():
        return {"final_present": False, "final_join_rate": 0.0}
    schema_names = set(pq.ParquetFile(final_path).schema.names)
    mapping = {
        "final_alert_label": "legacy_final_alert_label",
        "risk_bucket": "legacy_risk_bucket",
        "gating_label": "legacy_gating_label",
        "augmentation_label": "legacy_augmentation_label",
    }
    needed = ["event_id"] + [source for source in mapping if source in schema_names]
    if "event_id" not in schema_names:
        return {"final_present": True, "final_join_rate": 0.0}
    final = pd.read_parquet(final_path, columns=needed, engine="pyarrow").drop_duplicates("event_id")
    final = final.set_index("event_id")
    joined = df["event_id"].isin(final.index)
    for source, target in mapping.items():
        if source in final.columns:
            df[target] = df["event_id"].map(final[source]).fillna(MISSING)
    return {"final_present": True, "final_join_rate": safe_rate(int(joined.sum()), len(df))}


def build_vrp_index(vrp_path: Path | None) -> dict[str, list[tuple[int, int]]]:
    if vrp_path is None or not vrp_path.exists():
        return {}
    schema_names = set(pq.ParquetFile(vrp_path).schema.names)
    needed = [column for column in ["prefix", "asn", "max_length"] if column in schema_names]
    if len(needed) < 3:
        return {}
    vrp = pd.read_parquet(vrp_path, columns=needed, engine="pyarrow")
    index: dict[str, list[tuple[int, int]]] = {}
    for row in vrp.itertuples(index=False):
        try:
            network = ipaddress.ip_network(str(row.prefix), strict=False)
        except ValueError:
            continue
        asn = normalize_asn(row.asn)
        if asn is None:
            continue
        try:
            max_length = int(row.max_length)
        except (TypeError, ValueError):
            max_length = int(network.prefixlen)
        index.setdefault(str(network), []).append((asn, max_length))
    return index


def covering_vrps(prefix: str, vrp_index: dict[str, list[tuple[int, int]]]) -> list[tuple[int, int, int]]:
    if not vrp_index or not prefix or prefix.lower() in {MISSING, "none", "nan"}:
        return []
    try:
        network = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return []
    matches: list[tuple[int, int, int]] = []
    for prefix_len in range(int(network.prefixlen), -1, -1):
        try:
            candidate = network if prefix_len == network.prefixlen else network.supernet(new_prefix=prefix_len)
        except ValueError:
            continue
        for asn, max_length in vrp_index.get(str(candidate), []):
            matches.append((asn, max_length, int(network.prefixlen)))
    return matches


def classify_rpki(prefix: str, origin: Any, vrp_index: dict[str, list[tuple[int, int]]]) -> str:
    if not vrp_index:
        return "missing"
    asn = normalize_asn(origin)
    if asn is None:
        return "missing"
    matches = covering_vrps(prefix, vrp_index)
    if not matches:
        return "unknown"
    valid = any(vrp_asn == asn and route_len <= max_len for vrp_asn, max_len, route_len in matches)
    if valid:
        return "valid"
    origin_length_mismatch = any(vrp_asn == asn and route_len > max_len for vrp_asn, max_len, route_len in matches)
    if origin_length_mismatch:
        return "invalid_length"
    alternate_origin_cover = any(route_len <= max_len and vrp_asn != asn for vrp_asn, max_len, route_len in matches)
    if alternate_origin_cover:
        return "invalid_asn"
    return "invalid_length"


def attach_rpki_status(df: pd.DataFrame, vrp_path: Path | None) -> dict[str, Any]:
    vrp_index = build_vrp_index(vrp_path)
    if not vrp_index:
        df["rpki_status"] = "missing"
        return {"cache_present": False, "unique_prefix_origin_checked": 0}
    unique = df[["prefix", "origin_as", "prefix_origin_key"]].drop_duplicates("prefix_origin_key").copy()
    unique["rpki_status"] = [
        classify_rpki(str(prefix), origin, vrp_index)
        for prefix, origin in zip(unique["prefix"], unique["origin_as"])
    ]
    status_map = dict(zip(unique["prefix_origin_key"], unique["rpki_status"]))
    df["rpki_status"] = df["prefix_origin_key"].map(status_map).fillna("missing")
    return {"cache_present": True, "unique_prefix_origin_checked": int(len(unique))}


def derive_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    reason_text = lower_text(df["candidate_reasons"])
    candidate_flag = bool_series(df["candidate_flag"])
    path_seen_before = bool_series(df["path_seen_before"], default=True)
    collector_count = numeric_series(df["collector_count"])
    visibility_count = numeric_series(df["visibility_count"])
    matched_rule_count = numeric_series(df["matched_rule_count"])
    prefix_unique_origins = numeric_series(df["prefix_unique_origins"])
    po_collector_support = numeric_series(df["po_collector_support"])
    rel_unknown_cnt = numeric_series(df["rel_unknown_cnt"])
    duration_sec = numeric_series(df["duration_sec"])
    rpki_status = normalize_text(df["rpki_status"])

    reason_missing = reason_text.isin(["", "[]", MISSING, "none", "nan"])
    origin_novelty = contains_any(reason_text, ORIGIN_TOKENS) | prefix_unique_origins.gt(1)
    rpki_invalid = rpki_status.isin(["invalid_asn", "invalid_length"])
    path_novelty = contains_any(reason_text, PATH_TOKENS) | (~path_seen_before)
    path_length_anomaly = contains_any(reason_text, PATH_LENGTH_TOKENS)
    explicit_route_leak = contains_any(reason_text, ROUTE_LEAK_TOKENS)
    high_unknown_path_diag = rel_unknown_cnt.ge(3) & (path_novelty | path_length_anomaly | origin_novelty)
    route_leak_like = explicit_route_leak | high_unknown_path_diag
    low_visibility = (
        collector_count.le(1)
        | visibility_count.le(1)
        | contains_any(reason_text, ["single_collector_visibility", "unusually_low_visibility"])
    )
    collector_asymmetry = (
        contains_any(reason_text, ["cross_collector", "collector_asymmetry", "monitor_inconsistency"])
        | (low_visibility & po_collector_support.ge(2) & (path_novelty | origin_novelty | path_length_anomaly))
    )
    community_signal = contains_any(reason_text, COMMUNITY_TOKENS)
    stealth_visibility = low_visibility & (
        origin_novelty | path_novelty | path_length_anomaly | collector_asymmetry | community_signal
    )
    explicit_poisoning = contains_any(reason_text, POISONING_TOKENS)
    poisoning_proxy = low_visibility & path_novelty & duration_sec.le(60) & po_collector_support.ge(2)
    poisoning_evasion_like = explicit_poisoning | poisoning_proxy | (collector_asymmetry & path_novelty & candidate_flag)

    forged_origin_family = origin_novelty | (rpki_invalid & (path_novelty | low_visibility | ~reason_missing))
    route_leak_family = route_leak_like
    path_manipulation_family = path_novelty | path_length_anomaly
    stealth_visibility_family = stealth_visibility | community_signal
    poisoning_evasion_family = poisoning_evasion_like

    must_keep = (
        forged_origin_family
        | route_leak_family
        | path_manipulation_family
        | stealth_visibility_family
        | poisoning_evasion_family
    )

    weak_or_missing_reason = (
        reason_missing
        | (
            contains_any(reason_text, LOW_SPECIFICITY_TOKENS)
            & ~(origin_novelty | path_novelty | path_length_anomaly | explicit_route_leak | community_signal)
        )
    )
    no_external_protective_evidence = ~rpki_invalid & ~route_leak_family & ~community_signal
    obvious_low_info = (
        ~must_keep
        & weak_or_missing_reason
        & path_seen_before
        & prefix_unique_origins.le(1)
        & no_external_protective_evidence
    )

    policy_a = obvious_low_info & (~candidate_flag) & matched_rule_count.le(2)
    policy_b = obvious_low_info & matched_rule_count.le(2) & rel_unknown_cnt.le(2)
    policy_c = obvious_low_info & prefix_unique_origins.le(2)
    gray_zone = ~(must_keep | policy_a)

    return {
        "candidate_flag": candidate_flag,
        "path_seen_before": path_seen_before,
        "reason_missing": reason_missing,
        "origin_novelty": origin_novelty,
        "rpki_invalid": rpki_invalid,
        "path_novelty": path_novelty,
        "path_length_anomaly": path_length_anomaly,
        "route_leak_like": route_leak_like,
        "low_visibility": low_visibility,
        "collector_asymmetry": collector_asymmetry,
        "community_signal": community_signal,
        "poisoning_evasion_like": poisoning_evasion_like,
        "forged_origin_family": forged_origin_family,
        "route_leak_family": route_leak_family,
        "path_manipulation_family": path_manipulation_family,
        "stealth_visibility_family": stealth_visibility_family,
        "poisoning_evasion_family": poisoning_evasion_family,
        "must_keep": must_keep,
        "weak_or_missing_reason": weak_or_missing_reason,
        "obvious_low_info": obvious_low_info,
        "policy_A_very_conservative": policy_a,
        "policy_B_balanced": policy_b,
        "policy_C_aggressive": policy_c,
        "gray_zone_retained": gray_zone,
    }


def mask_reasons(index: Any, masks: dict[str, pd.Series], names: list[str]) -> list[str]:
    return [name for name in names if bool(masks[name].loc[index])]


def reason_json(sample: pd.DataFrame, masks: dict[str, pd.Series], names: list[str]) -> list[str]:
    return [json.dumps(mask_reasons(index, masks, names), ensure_ascii=False) for index in sample.index]


def family_json(sample: pd.DataFrame, masks: dict[str, pd.Series]) -> list[str]:
    names = [
        "forged_origin_family",
        "route_leak_family",
        "path_manipulation_family",
        "stealth_visibility_family",
        "poisoning_evasion_family",
    ]
    return [json.dumps(mask_reasons(index, masks, names), ensure_ascii=False) for index in sample.index]


def write_noise_feature_availability(
    df: pd.DataFrame,
    masks: dict[str, pd.Series],
    paths: dict[str, Path | None],
    event_info: dict[str, Any],
    final_info: dict[str, Any],
    rpki_info: dict[str, Any],
    output_dir: Path,
) -> pd.DataFrame:
    total = len(df)
    rows = [
        ("candidate_flag", paths["candidates"], True, non_missing_rate(df["candidate_flag"]), "legacy foreground flag; workflow signal only"),
        ("candidate_reasons", paths["candidates"], True, non_missing_rate(df["candidate_reasons"]), "weak signal provenance; not truth labels"),
        ("prefix_origin_key", paths["candidates"], True, non_missing_rate(df["prefix_origin_key"]), "lookup key; not verdict"),
        ("path_seen_before", paths["candidates"], True, non_missing_rate(df["path_seen_before"]), "path novelty proxy"),
        ("collector_visibility", paths["candidates"], True, min(non_missing_rate(df["collector_count"]), non_missing_rate(df["visibility_count"])), "monitor visibility proxy"),
        ("event_time_scope", paths["events"], bool(event_info.get("events_present")), min(non_missing_rate(df["first_seen"]), non_missing_rate(df["last_seen"])), "clean-window and temporal profile support"),
        ("asrel_diagnostic_fields", paths["events"], bool(event_info.get("rel_fields_present")), float(event_info.get("event_join_rate", 0.0)), "diagnostic only; AS-rel diagnostic is not route leak truth"),
        ("rpki_status", paths["rpki"], bool(rpki_info.get("cache_present")), safe_rate(int(normalize_text(df["rpki_status"]).isin(["valid", "invalid_asn", "invalid_length"]).sum()), total), "RPKI invalid is not attack truth; RPKI valid is not benign"),
        ("legacy_final_reference", paths["final"], bool(final_info.get("final_present")), float(final_info.get("final_join_rate", 0.0)), "legacy labels are workflow references, not truth"),
        ("communities_no_export", None, False, 0.0, "not propagated to candidate-entry in current run; NO_EXPORT absent is not safe"),
        ("poisoning_evasion_proxy", paths["candidates"], True, safe_rate(int(masks["poisoning_evasion_like"].sum()), total), "retention proxy only; not confirmed poisoning"),
    ]
    availability = pd.DataFrame(
        [
            {
                "feature": feature,
                "source_path": str(path) if path else MISSING,
                "available": available,
                "coverage_rate": round(float(coverage), 6),
                "notes": notes,
            }
            for feature, path, available, coverage, notes in rows
        ]
    )
    availability.to_csv(output_dir / "noise_feature_availability.csv", index=False)
    return availability


def write_must_keep_coverage(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path) -> pd.DataFrame:
    total = len(df)
    families = [
        ("forged_origin", "new origin, unseen prefix-origin, or RPKI invalid combined with weak signal", "forged_origin_family", "suspicious_forged_origin candidate, not confirmed hijack"),
        ("route_leak", "valley-like, AS-rel diagnostic, suspect triplet, or high unknown relation plus path/origin novelty", "route_leak_family", "suspicious_route_leak candidate, not route leak truth"),
        ("path_manipulation", "unseen path, unseen exact path, path pattern change, or abnormal path length", "path_manipulation_family", "suspicious_path_manipulation candidate, not confirmed manipulation"),
        ("stealth_visibility", "low visibility with another weak signal, collector asymmetry, or community/NO_EXPORT hint", "stealth_visibility_family", "suspicious_stealth_visibility candidate, not confirmed stealth or NO_EXPORT"),
        ("poisoning_evasion", "explicit poisoning/evasion token or crafted-looking low-visibility path-novelty proxy", "poisoning_evasion_family", "poisoning_or_evasion_suspected candidate, not confirmed poisoning"),
    ]
    rows = []
    for family, definition, mask_name, allowed_claim in families:
        mask = masks[mask_name]
        rows.append(
            {
                "attack_family": family,
                "must_keep_signal_definition": definition,
                "hit_count": int(mask.sum()),
                "hit_rate": safe_rate(int(mask.sum()), total),
                "suppressed_by_policy_A": int((mask & masks["policy_A_very_conservative"]).sum()),
                "suppressed_by_policy_B": int((mask & masks["policy_B_balanced"]).sum()),
                "suppressed_by_policy_C": int((mask & masks["policy_C_aggressive"]).sum()),
                "allowed_claim": allowed_claim,
                "forbidden_claim": "confirmed attack or benign truth",
            }
        )
    coverage = pd.DataFrame(rows)
    coverage.to_csv(output_dir / "multi_attack_must_keep_coverage.csv", index=False)
    return coverage


def policy_metrics(df: pd.DataFrame, masks: dict[str, pd.Series], policy_name: str, description: str) -> dict[str, Any]:
    total = len(df)
    suppress = masks[policy_name]
    keep = ~suppress
    must_keep = masks["must_keep"]
    gray = keep & ~must_keep
    legacy_high = normalize_text(df["legacy_final_alert_label"]).eq("high_priority_alert")
    legacy_needs = normalize_text(df["legacy_final_alert_label"]).eq("needs_review")
    poisoning = masks["poisoning_evasion_like"]
    must_keep_suppressed = int((suppress & must_keep).sum())
    poisoning_suppressed = int((suppress & poisoning).sum())
    legacy_high_suppressed = int((suppress & legacy_high).sum())
    stop_loss = bool(must_keep_suppressed or poisoning_suppressed or legacy_high_suppressed)
    would_suppress = int(suppress.sum())
    would_keep = int(keep.sum())
    stop_reasons = []
    if must_keep_suppressed:
        stop_reasons.append("must_keep_suppressed")
    if poisoning_suppressed:
        stop_reasons.append("poisoning_evasion_like_suppressed")
    if legacy_high_suppressed:
        stop_reasons.append("legacy_high_reference_suppressed")
    return {
        "policy_id": policy_name,
        "policy_description": description,
        "would_suppress_count": would_suppress,
        "would_suppress_rate": safe_rate(would_suppress, total),
        "would_keep_count": would_keep,
        "must_keep_hit_count": int(must_keep.sum()),
        "must_keep_suppressed_count": must_keep_suppressed,
        "must_keep_suppression_rate": safe_rate(must_keep_suppressed, int(must_keep.sum())),
        "gray_zone_count": int(gray.sum()),
        "gray_zone_rate": safe_rate(int(gray.sum()), total),
        "estimated_compression_ratio": round(float(total) / float(would_keep), 6) if would_keep else 0.0,
        "legacy_high_suppressed_count": legacy_high_suppressed,
        "legacy_needs_suppressed_count": int((suppress & legacy_needs).sum()),
        "poisoning_evasion_like_suppressed_count": poisoning_suppressed,
        "stop_loss_triggered": stop_loss,
        "stop_loss_reason": ";".join(stop_reasons) if stop_reasons else "none",
    }


def write_counterfactual_policy_audit(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path) -> pd.DataFrame:
    rows = [
        policy_metrics(df, masks, "policy_A_very_conservative", "Suppress only non-foreground low-information rows with no must-keep signal."),
        policy_metrics(df, masks, "policy_B_balanced", "Suppress low-information rows with no must-keep signal and low AS-rel uncertainty."),
        policy_metrics(df, masks, "policy_C_aggressive", "Suppress all low-information rows with no must-keep signal; upper-bound stress test only."),
    ]
    audit = pd.DataFrame(rows)
    audit.to_csv(output_dir / "counterfactual_suppression_policy_audit.csv", index=False)
    return audit


def write_clean_window_profile(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path, top_n: int = 20) -> pd.DataFrame:
    total = len(df)
    reason_counts = normalize_text(df["candidate_reasons"]).value_counts(dropna=False).head(top_n)
    prefix_counts = normalize_text(df["prefix_origin_key"]).value_counts(dropna=False)
    path_counts = normalize_text(df["as_path_clean"]).value_counts(dropna=False)
    single_short = masks["low_visibility"] & numeric_series(df["duration_sec"]).le(60)
    candidate_flag = masks["candidate_flag"]
    stable_weak = (
        candidate_flag
        & masks["path_seen_before"]
        & numeric_series(df["prefix_unique_origins"]).le(1)
        & ~masks["origin_novelty"]
        & ~masks["path_novelty"]
    )
    rows = [
        {"metric": "total_candidate_entry_rows", "value": total, "rate": 1.0, "notes": "candidate-entry audit denominator"},
        {"metric": "candidate_flag_true_rows", "value": int(candidate_flag.sum()), "rate": safe_rate(int(candidate_flag.sum()), total), "notes": "legacy foreground flag, not truth"},
        {"metric": "candidate_flag_false_rows", "value": int((~candidate_flag).sum()), "rate": safe_rate(int((~candidate_flag).sum()), total), "notes": "likely first obvious-noise source if no must-keep signal"},
        {"metric": "single_collector_short_rows", "value": int(single_short.sum()), "rate": safe_rate(int(single_short.sum()), total), "notes": "clean-window volatility profile"},
        {"metric": "weak_or_missing_reason_rows", "value": int(masks["weak_or_missing_reason"].sum()), "rate": safe_rate(int(masks["weak_or_missing_reason"].sum()), total), "notes": "low semantic information, not benign"},
        {"metric": "repeated_prefix_origin_rows", "value": int(df["prefix_origin_key"].map(prefix_counts).gt(1).sum()), "rate": safe_rate(int(df["prefix_origin_key"].map(prefix_counts).gt(1).sum()), total), "notes": "repeat pressure in clean window"},
        {"metric": "repeated_path_signature_rows", "value": int(df["as_path_clean"].astype(str).map(path_counts).gt(1).sum()), "rate": safe_rate(int(df["as_path_clean"].astype(str).map(path_counts).gt(1).sum()), total), "notes": "repeated AS path pressure"},
        {"metric": "historically_stable_weak_candidate_rows", "value": int(stable_weak.sum()), "rate": safe_rate(int(stable_weak.sum()), total), "notes": "candidate_flag true but weak novelty evidence under current proxies"},
    ]
    for idx, (reason, count) in enumerate(reason_counts.items(), start=1):
        rows.append({"metric": f"top_candidate_reason_{idx:02d}", "value": int(count), "rate": safe_rate(int(count), total), "notes": str(reason)})
    profile = pd.DataFrame(rows)
    profile.to_csv(output_dir / "clean_window_noise_profile.csv", index=False)
    return profile


def write_legacy_reference_audit(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path) -> pd.DataFrame:
    total = len(df)
    label = normalize_text(df["legacy_final_alert_label"])
    rows = []
    for legacy_label in ["high_priority_alert", "needs_review", "low_priority_or_background", MISSING]:
        label_mask = label.eq(legacy_label)
        rows.append(
            {
                "legacy_reference_label": legacy_label,
                "row_count": int(label_mask.sum()),
                "row_rate": safe_rate(int(label_mask.sum()), total),
                "must_keep_count": int((label_mask & masks["must_keep"]).sum()),
                "policy_A_would_suppress_count": int((label_mask & masks["policy_A_very_conservative"]).sum()),
                "policy_B_would_suppress_count": int((label_mask & masks["policy_B_balanced"]).sum()),
                "policy_C_would_suppress_count": int((label_mask & masks["policy_C_aggressive"]).sum()),
                "notes": "legacy labels are workflow references, not truth",
            }
        )
    audit = pd.DataFrame(rows)
    audit.to_csv(output_dir / "legacy_signal_reference_audit.csv", index=False)
    return audit


def write_poisoning_retention_audit(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path) -> pd.DataFrame:
    total = len(df)
    explicit = contains_any(lower_text(df["candidate_reasons"]), POISONING_TOKENS)
    signal_rows = [
        ("explicit_poisoning_evasion_token", explicit),
        ("crafted_low_visibility_path_novelty_proxy", masks["poisoning_evasion_like"] & ~explicit),
        ("any_poisoning_evasion_like_signal", masks["poisoning_evasion_like"]),
    ]
    rows = []
    for signal_name, signal_mask in signal_rows:
        rows.append(
            {
                "signal": signal_name,
                "hit_count": int(signal_mask.sum()),
                "hit_rate": safe_rate(int(signal_mask.sum()), total),
                "policy_A_suppressed_count": int((signal_mask & masks["policy_A_very_conservative"]).sum()),
                "policy_B_suppressed_count": int((signal_mask & masks["policy_B_balanced"]).sum()),
                "policy_C_suppressed_count": int((signal_mask & masks["policy_C_aggressive"]).sum()),
                "retention_guardrail": "any poisoning/evasion-like signal must not be suppressed in R-NOISE-0",
                "forbidden_claim": "confirmed poisoning or confirmed evasion",
            }
        )
    audit = pd.DataFrame(rows)
    audit.to_csv(output_dir / "poisoning_evasion_retention_audit.csv", index=False)
    return audit


def write_samples(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path, sample_size: int) -> None:
    base_columns = [
        "event_id",
        "prefix",
        "origin_as",
        "collector_count",
        "visibility_count",
        "candidate_flag",
        "candidate_reasons",
        "matched_rule_count",
        "path_seen_before",
        "rpki_status",
        "rel_unknown_cnt",
        "legacy_final_alert_label",
    ]
    columns = [column for column in base_columns if column in df.columns]
    must_keep_sample = df.loc[masks["must_keep"], columns].head(sample_size).copy()
    must_keep_sample["must_keep_family_set"] = family_json(must_keep_sample, masks)
    must_keep_sample["must_keep_reason_set"] = reason_json(
        must_keep_sample,
        masks,
        ["origin_novelty", "rpki_invalid", "path_novelty", "path_length_anomaly", "route_leak_like", "stealth_visibility_family", "poisoning_evasion_like"],
    )
    must_keep_sample.to_csv(output_dir / "must_keep_foreground_audit.csv", index=False)

    suppress_sample = df.loc[masks["policy_A_very_conservative"], columns].head(sample_size).copy()
    suppress_sample["policy_id"] = "policy_A_very_conservative"
    suppress_sample["suppressible_reason_set"] = reason_json(suppress_sample, masks, ["weak_or_missing_reason", "obvious_low_info"])
    suppress_sample["misuse_boundary"] = "may-suppress is operational, not confirmed benign"
    suppress_sample.to_csv(output_dir / "may_suppress_background_audit.csv", index=False)

    gray_sample = df.loc[masks["gray_zone_retained"], columns].head(sample_size).copy()
    gray_sample["gray_zone_reason"] = "not must-keep, but not safe obvious noise under policy_A"
    gray_sample["retention_action"] = "gray_zone_retained"
    gray_sample.to_csv(output_dir / "gray_zone_retained_audit.csv", index=False)


def choose_recommended_next_step(policy_audit: pd.DataFrame) -> dict[str, Any]:
    safe = policy_audit[~policy_audit["stop_loss_triggered"]].copy()
    if safe.empty:
        return {
            "decision": "stop_loss_do_not_enter_R_NOISE_1",
            "recommended_next_step": "repair feature semantics and rerun R-NOISE-0",
            "reason": "all counterfactual policies suppress must-keep, poisoning/evasion-like, or legacy-high reference rows",
        }
    policy_a = safe[safe["policy_id"].eq("policy_A_very_conservative")]
    if not policy_a.empty and float(policy_a.iloc[0]["would_suppress_rate"]) >= 0.05:
        best = policy_a.iloc[0]
    else:
        best = safe.sort_values(["would_suppress_rate", "must_keep_suppression_rate"], ascending=[False, True]).iloc[0]
    if float(best["would_suppress_rate"]) < 0.05:
        return {
            "decision": "stop_loss_insufficient_safe_compression",
            "recommended_next_step": "family/foreground feature repair before R-NOISE-1",
            "reason": "safe policy exists but suppresses too little to justify implementation",
        }
    return {
        "decision": "eligible_for_R_NOISE_1_conservative_smoke",
        "recommended_next_step": f"R-NOISE-1 foreground extraction smoke using {best['policy_id']} with must-keep guards",
        "reason": "a counterfactual policy suppresses operational noise without hitting must-keep or poisoning/evasion-like guards",
        "best_safe_policy": str(best["policy_id"]),
        "best_safe_policy_suppress_rate": float(best["would_suppress_rate"]),
        "best_safe_policy_compression_ratio": float(best["estimated_compression_ratio"]),
    }


def df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    columns = list(df.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in df.to_dict("records"):
        values = [str(row.get(column, "")).replace("|", "/") for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(
    output_dir: Path,
    run_id: str,
    summary: dict[str, Any],
    policy_audit: pd.DataFrame,
    must_keep_coverage: pd.DataFrame,
) -> None:
    best = summary["stop_loss_assessment"]
    lines = [
        "# R-NOISE-0 Obvious Noise Separability Audit",
        "",
        "This report is generated by `scripts/audit_obvious_noise_separability.py`.",
        "",
        "## Scope",
        "",
        "- R-NOISE-0 is a read-only obvious noise separability audit.",
        "- It simulates counterfactual suppression policies but does not delete candidates.",
        "- It does not train learning, modify the old seven-layer pipeline, or create truth labels.",
        "- `background_noise` / may-suppress means operational suppression candidate, not confirmed benign.",
        "- RPKI invalid is not attack truth.",
        "- AS-rel diagnostic is not route leak truth.",
        "",
        "## Run Summary",
        "",
        f"- run_id: `{run_id}`",
        f"- candidate_entry_rows: `{summary['candidate_entry_rows']}`",
        f"- must_keep_count: `{summary['must_keep_count']}` (`{summary['must_keep_rate']}`)",
        f"- gray_zone_count under policy_A: `{summary['gray_zone_count']}` (`{summary['gray_zone_rate']}`)",
        f"- recommended decision: `{best['decision']}`",
        f"- recommended next step: `{best['recommended_next_step']}`",
        "",
        "## Counterfactual Policy Results",
        "",
        df_to_markdown(policy_audit),
        "",
        "## Multi-Attack Must-Keep Coverage",
        "",
        df_to_markdown(must_keep_coverage),
        "",
        "## Interpretation",
        "",
        "R-NOISE-0's target is not to find the largest possible background set. The target is to find only safely suppressible obvious background. If compression and must-keep protection cannot both pass, the pipeline must stop before R-NOISE-1.",
        "",
        "Poisoning/evasion robustness is core. Any poisoning/evasion-like signal is retained in this audit even when it only appears as a proxy rather than confirmed poisoning.",
        "",
    ]
    (output_dir / "noise_separability_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_noise_0" / args.run_id
    prepare_output_dir(output_dir, args.overwrite)

    candidates_path = paths["candidates"]
    assert candidates_path is not None
    df = load_candidates(candidates_path)
    event_info = attach_event_fields(df, paths["events"])
    final_info = attach_legacy_final_reference(df, paths["final"])
    rpki_info = attach_rpki_status(df, paths["rpki"])
    masks = derive_masks(df)

    availability = write_noise_feature_availability(df, masks, paths, event_info, final_info, rpki_info, output_dir)
    must_keep_coverage = write_must_keep_coverage(df, masks, output_dir)
    policy_audit = write_counterfactual_policy_audit(df, masks, output_dir)
    clean_profile = write_clean_window_profile(df, masks, output_dir)
    legacy_audit = write_legacy_reference_audit(df, masks, output_dir)
    poisoning_audit = write_poisoning_retention_audit(df, masks, output_dir)
    write_samples(df, masks, output_dir, args.sample_size)

    total = len(df)
    must_keep_count = int(masks["must_keep"].sum())
    policy_a = masks["policy_A_very_conservative"]
    gray_count = int(masks["gray_zone_retained"].sum())
    stop_loss = choose_recommended_next_step(policy_audit)
    rpki_status_dist = {
        str(key): int(value)
        for key, value in normalize_text(df["rpki_status"]).value_counts(dropna=False).to_dict().items()
    }
    summary = {
        "phase": "R-NOISE-0",
        "status": "completed",
        "run_id": args.run_id,
        "candidate_entry_path": str(candidates_path),
        "candidate_entry_rows": total,
        "input_inventory": {
            "candidates": parquet_info(paths["candidates"]),
            "events": parquet_info(paths["events"]),
            "scores": parquet_info(paths["scores"]),
            "final": parquet_info(paths["final"]),
            "rpki": parquet_info(paths["rpki"]),
            "r_agg_3_summary_present": bool(paths["r_agg_3_summary"]),
            "r_evid_0_summary_present": bool(paths["r_evid_0_summary"]),
        },
        "feature_availability_rate_by_type": {
            str(row["feature"]): float(row["coverage_rate"]) for row in availability.to_dict("records")
        },
        "candidate_flag_true_count": int(masks["candidate_flag"].sum()),
        "candidate_flag_true_rate": safe_rate(int(masks["candidate_flag"].sum()), total),
        "must_keep_count": must_keep_count,
        "must_keep_rate": safe_rate(must_keep_count, total),
        "policy_A_suppressible_count": int(policy_a.sum()),
        "policy_A_suppressible_rate": safe_rate(int(policy_a.sum()), total),
        "gray_zone_count": gray_count,
        "gray_zone_rate": safe_rate(gray_count, total),
        "multi_attack_must_keep_counts": {
            "suspicious_forged_origin": int(masks["forged_origin_family"].sum()),
            "suspicious_route_leak": int(masks["route_leak_family"].sum()),
            "suspicious_path_manipulation": int(masks["path_manipulation_family"].sum()),
            "suspicious_stealth_visibility": int(masks["stealth_visibility_family"].sum()),
            "poisoning_or_evasion_suspected": int(masks["poisoning_evasion_family"].sum()),
        },
        "counterfactual_policy_summary": policy_audit.to_dict("records"),
        "legacy_reference_summary": legacy_audit.to_dict("records"),
        "poisoning_evasion_retention_summary": poisoning_audit.to_dict("records"),
        "rpki_status_distribution": rpki_status_dist,
        "rpki_cache_present": bool(rpki_info.get("cache_present")),
        "event_join_rate": float(event_info.get("event_join_rate", 0.0)),
        "final_reference_join_rate": float(final_info.get("final_join_rate", 0.0)),
        "clean_window_noise_profile_key_metrics": clean_profile.head(8).to_dict("records"),
        "stop_loss_assessment": stop_loss,
        "truth_safety_statement": {
            "no_truth_label": True,
            "background_like_is_benign": False,
            "rpki_invalid_is_attack_truth": False,
            "asrel_diagnostic_is_route_leak_truth": False,
            "legacy_labels_are_truth": False,
            "trained_learning": False,
            "implemented_suppression": False,
            "modified_old_pipeline": False,
        },
        "output_files": OUTPUT_FILES,
    }
    with (output_dir / "r_noise_0_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    write_report(output_dir, args.run_id, summary, policy_audit, must_keep_coverage)

    print(
        json.dumps(
            {
                "status": "completed",
                "phase": "R-NOISE-0",
                "candidate_entry_rows": total,
                "must_keep_rate": summary["must_keep_rate"],
                "policy_A_suppressible_rate": summary["policy_A_suppressible_rate"],
                "decision": stop_loss["decision"],
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
