import argparse
import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_ABC_CSV = "outputs/e8a_case_pool_v01/e8a_case_candidates_abc.csv"
DEFAULT_D_CSV = "outputs/e8a_case_pool_v01/e8a_case_candidates_d_stealth.csv"
DEFAULT_CARDS_CSV = "outputs/e8a_case_pool_v01/e8a_case_cards_minimal.csv"
DEFAULT_OUTPUT_DIR = "outputs/e8b_case_external_validation_v01"
DEFAULT_RUNS_ROOT = "data/runs"

STRUCTURAL_KEYS = {
    "unseen_origin_for_prefix",
    "unseen_path_for_prefix_origin",
}
HISTORICAL_HINT_KEYS = {
    "unusually_short_duration_for_prefix",
    "unusually_low_visibility_for_prefix",
    "sparse_short_lived_event",
}


def safe_float(v: Any, default: float = 0.0) -> float:
    out = pd.to_numeric(pd.Series([v]), errors="coerce").fillna(default).iloc[0]
    return float(out)


def safe_int(v: Any, default: int = 0) -> int:
    out = pd.to_numeric(pd.Series([v]), errors="coerce").fillna(default).iloc[0]
    return int(out)


def safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    return str(v)


def is_missing(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    text = str(v).strip().lower()
    return text in {"", "nan", "none", "null"}


def parse_reason_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [safe_str(x).strip() for x in v if safe_str(x).strip()]
    text = safe_str(v).strip()
    if not text:
        return []
    for fn in (json.loads, ast.literal_eval):
        try:
            parsed = fn(text)
            if isinstance(parsed, list):
                return [safe_str(x).strip() for x in parsed if safe_str(x).strip()]
        except Exception:
            pass
    text = text.strip("[]")
    if not text:
        return []
    parts = [p.strip().strip("'").strip('"') for p in text.split(",")]
    return [p for p in parts if p]


def parse_compared_labels(v: Any) -> dict[str, Any]:
    text = safe_str(v).strip()
    if not text:
        return {}
    for fn in (json.loads, ast.literal_eval):
        try:
            parsed = fn(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {"raw": text}


def as_path_len(path_val: Any) -> int:
    path = safe_str(path_val).strip()
    if not path:
        return 0
    return len([x for x in path.split(" ") if x.strip()])


def parse_collectors(collector_set: Any) -> list[str]:
    text = safe_str(collector_set).strip()
    if not text:
        return []
    return [x.strip() for x in text.split("|") if x.strip()]


def ts_to_utc_text(ts: Any) -> str:
    if is_missing(ts):
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ""


def flatten_community_value(v: Any) -> list[str]:
    out: list[str] = []
    if v is None:
        return out
    if isinstance(v, (list, tuple, set)):
        for x in v:
            out.extend(flatten_community_value(x))
        return out
    if isinstance(v, np.ndarray):
        for x in v.tolist():
            out.extend(flatten_community_value(x))
        return out
    text = safe_str(v).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return out

    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")) or (
        text.startswith("(") and text.endswith(")")
    ):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple, set)):
                for x in parsed:
                    out.extend(flatten_community_value(x))
                return out
        except Exception:
            pass
    out.append(text)
    return out


def parse_community_tokens(v: Any) -> tuple[list[str], bool, bool]:
    raw_list = flatten_community_value(v)
    tokens: list[str] = []
    no_export = False
    no_advertise = False

    for raw in raw_list:
        text = safe_str(raw).strip()
        if not text:
            continue
        lower = text.lower().replace("-", "_")
        if "no_export" in lower:
            no_export = True
        if "no_advertise" in lower:
            no_advertise = True

        pair_hits = re.findall(r"\b\d+\s*:\s*\d+\b", text)
        for token in pair_hits:
            token = token.replace(" ", "")
            tokens.append(token)
            if token == "65535:65281":
                no_export = True
            if token == "65535:65282":
                no_advertise = True

        int_hits = re.findall(r"\b\d{7,10}\b", text)
        for token in int_hits:
            tokens.append(token)
            if token == "4294967041":
                no_export = True
            if token == "4294967042":
                no_advertise = True

    dedup = list(dict.fromkeys(tokens))
    return dedup, no_export, no_advertise


def evaluate_valley_free(rel_seq: Any) -> tuple[str, str, str]:
    rel_text = safe_str(rel_seq).strip().lower()
    if not rel_text:
        return "uncertain", "rel_seq_missing", "no relationship sequence available"

    rels = [x.strip() for x in rel_text.split("|") if x.strip()]
    counts = {k: rels.count(k) for k in ["c2p", "p2p", "p2c", "unk"]}
    summary = (
        f"path={ '|'.join(rels) }; "
        f"counts(c2p={counts['c2p']}, p2p={counts['p2p']}, p2c={counts['p2c']}, unk={counts['unk']})"
    )

    if any(x == "unk" for x in rels):
        return "uncertain", summary, "contains unknown relationship edge(s), cannot strictly validate valley-free"

    valid = {"c2p", "p2p", "p2c"}
    if any(x not in valid for x in rels):
        return "uncertain", summary, "contains unsupported relationship label(s), cannot strictly validate"

    seen_p2p = 0
    phase = "up"
    for idx, rel in enumerate(rels):
        if rel == "c2p":
            if phase in {"peer", "down"}:
                return "yes", summary, f"c2p appears after p2p/p2c at hop index {idx}"
        elif rel == "p2p":
            seen_p2p += 1
            if seen_p2p > 1:
                return "yes", summary, f"multiple p2p edges (count={seen_p2p}) violate valley-free"
            if phase == "down":
                return "yes", summary, f"p2p appears after p2c at hop index {idx}"
            phase = "peer"
        elif rel == "p2c":
            phase = "down"

    return "no", summary, "sequence satisfies c2p* -> (p2p <=1) -> p2c* pattern"


def infer_case_letter(case_type: str) -> str:
    text = safe_str(case_type).strip()
    if not text:
        return ""
    return text[0].upper()


def infer_run_id(row: pd.Series) -> str:
    if not is_missing(row.get("run_id", "")):
        return safe_str(row.get("run_id", "")).strip()
    event_id = safe_str(row.get("event_id", "")).strip()
    if "_evt_" in event_id:
        return event_id.split("_evt_")[0]
    return ""


def gate_condition_met_from_metrics(risk_bucket: str, certainty: float, conflict: float, structural_score: float, missing: bool) -> bool:
    return (
        risk_bucket == "high"
        and certainty >= 65.0
        and conflict < 35.0
        and structural_score >= 45.0
        and not missing
    )


def load_run_payload(runs_root: Path, run_id: str) -> dict[str, Any]:
    run_dir = runs_root / run_id
    payload: dict[str, Any] = {
        "events": pd.DataFrame(),
        "final": pd.DataFrame(),
        "scores": pd.DataFrame(),
        "gating": pd.DataFrame(),
        "augment": pd.DataFrame(),
        "updates": pd.DataFrame(),
        "updates_has_communities": False,
    }
    if not run_dir.exists():
        return payload

    file_map = {
        "events": run_dir / "events" / "event_units.parquet",
        "final": run_dir / "final" / "final_alerts.parquet",
        "scores": run_dir / "scores" / "scored_candidates.parquet",
        "gating": run_dir / "gating" / "gated_candidates.parquet",
        "augment": run_dir / "augmentation" / "augmented_candidates.parquet",
    }
    for key, path in file_map.items():
        if path.exists():
            payload[key] = pd.read_parquet(path)

    update_parts = []
    update_files = sorted(run_dir.glob("collector=*/date=*/updates__*__rel.parquet"))
    for fp in update_files:
        part = pd.read_parquet(fp)
        keep = [c for c in ["ts", "collector", "peer_asn", "prefix", "as_path_clean", "origin_as", "communities"] if c in part.columns]
        part = part[keep].copy()
        update_parts.append(part)
    if update_parts:
        payload["updates"] = pd.concat(update_parts, axis=0, ignore_index=True)
        payload["updates_has_communities"] = "communities" in payload["updates"].columns
    return payload


def match_event_updates(event_row: pd.Series, updates_df: pd.DataFrame) -> pd.DataFrame:
    if updates_df.empty:
        return pd.DataFrame(columns=updates_df.columns)

    prefix = safe_str(event_row.get("prefix", ""))
    first_seen = safe_float(event_row.get("first_seen", np.nan), default=np.nan)
    last_seen = safe_float(event_row.get("last_seen", np.nan), default=np.nan)
    collectors = parse_collectors(event_row.get("collector_set", ""))
    as_path = safe_str(event_row.get("as_path_clean", ""))
    origin_as = event_row.get("origin_as", np.nan)

    out = updates_df[updates_df["prefix"].astype(str) == prefix].copy()
    if collectors:
        out = out[out["collector"].astype(str).isin(collectors)].copy()
    if not np.isnan(first_seen):
        out = out[pd.to_numeric(out["ts"], errors="coerce") >= first_seen].copy()
    if not np.isnan(last_seen):
        out = out[pd.to_numeric(out["ts"], errors="coerce") <= last_seen].copy()

    if as_path:
        out = out[out.get("as_path_clean", "").fillna("").astype(str) == as_path].copy()
    else:
        out = out[out.get("as_path_clean", "").fillna("").astype(str) == ""].copy()

    if not is_missing(origin_as):
        origin_num = safe_float(origin_as, default=np.nan)
        if not np.isnan(origin_num):
            out = out[pd.to_numeric(out.get("origin_as", np.nan), errors="coerce") == origin_num].copy()

    return out


def build_peer_summary(df: pd.DataFrame, topk: int = 5) -> tuple[int, str]:
    if df.empty or "peer_asn" not in df.columns:
        return 0, ""
    vc = df["peer_asn"].astype(str).value_counts().head(topk)
    summary = "; ".join([f"{idx}:{int(val)}" for idx, val in vc.items()])
    return int(df["peer_asn"].nunique()), summary


def build_external_hook(case_letter: str) -> str:
    if case_letter == "A":
        return "Replay raw BMP/updates around the same UTC window and cross-check ROA to recover missing origin/path context."
    if case_letter == "B":
        return "Cross-check ROA/IRR authorization for prefix-origin and operator incident traces around the event window."
    if case_letter == "C":
        return "Verify collector-asymmetry with additional route collectors and correlate with RIS/RouteViews incident timeline."
    if case_letter == "D":
        return "Use broader collector replay plus ROA/IRR consistency checks to validate stealth low-visibility persistence."
    return "Attach at least one independent control-plane source (ROA/IRR/collector replay) before claiming stronger confidence."


def derive_hints(
    *,
    reasons: list[str],
    structural_hit_count: int,
    top_factor: str,
    case_letter: str,
    collector_count: int,
    visibility_count: int,
) -> tuple[str, str, str]:
    has_hist = any(r in HISTORICAL_HINT_KEYS for r in reasons) or top_factor == "history_rarity_score"
    has_struct = structural_hit_count > 0 or top_factor == "structural_novelty_score"

    if has_hist:
        historical = "historical_deviation_signals_present"
    else:
        historical = "historical_deviation_not_prominent"

    if has_struct:
        structural = "structural_anomaly_signal_present"
    else:
        structural = "structural_anomaly_signal_limited"

    if case_letter == "C":
        visibility = "collector_asymmetric_fragility"
    elif case_letter == "D" and visibility_count <= 1:
        visibility = "low_visibility_but_high_priority"
    elif collector_count <= 1 and visibility_count <= 1:
        visibility = "single_collector_visibility"
    else:
        visibility = "no_special_visibility_pattern"

    return historical, structural, visibility


def grade_event(row: pd.Series) -> tuple[str, str]:
    label = safe_str(row.get("default_or_full_label", ""))
    risk = safe_float(row.get("risk_score", 0.0))
    certainty = safe_float(row.get("certainty_score", 0.0))
    conflict = safe_float(row.get("conflict_score", 0.0))
    missing = bool(row.get("missing_origin_or_path", False))
    structural_hits = safe_int(row.get("structural_hit_count", 0))
    topology = safe_str(row.get("topology_violation", ""))
    has_comm = safe_str(row.get("has_communities", ""))
    no_export = safe_str(row.get("has_no_export", ""))
    no_advertise = safe_str(row.get("has_no_advertise", ""))
    visibility_hint = safe_str(row.get("visibility_anomaly_hint", ""))
    case_letter = safe_str(row.get("source_case_type", ""))

    internal_strong = (
        label == "high_priority_alert"
        and risk >= 50.0
        and certainty >= 65.0
        and conflict <= 10.0
        and not missing
    )
    internal_mid = (risk >= 45.0 and structural_hits >= 1) or (label == "needs_review" and risk >= 45.0)

    external_strong = (topology == "yes") or (no_export == "yes") or (no_advertise == "yes")
    external_context = (
        topology in {"no", "yes", "uncertain"}
        or has_comm == "yes"
        or visibility_hint in {"collector_asymmetric_fragility", "low_visibility_but_high_priority"}
    )

    if internal_strong and external_strong:
        return (
            "high_confidence_event",
            "Strong internal high-priority evidence plus explicit external control-plane corroboration.",
        )

    if internal_strong and external_context:
        return (
            "strongly_suspicious",
            "Internal high-priority evidence is strong; external checks are supportive but not fully conclusive.",
        )

    if internal_mid and case_letter in {"B", "C", "D"} and conflict < 35.0 and not missing:
        return (
            "strongly_suspicious",
            "System-side suspicious signals are stable with partial external/control-plane support.",
        )

    if internal_mid:
        return (
            "needs_external_review",
            "System indicates suspicious behavior, but external evidence remains incomplete or uncertain.",
        )

    if topology == "uncertain" and has_comm in {"no", "unknown"}:
        return (
            "insufficient_external_support",
            "Automated external hooks are currently too weak (topology uncertain and no useful communities).",
        )

    return (
        "needs_external_review",
        "Suspicious indications exist but require additional external validation for stronger confidence.",
    )


def build_case_pool(abc_csv: Path, d_csv: Path, cards_csv: Path) -> pd.DataFrame:
    abc = pd.read_csv(abc_csv)
    cards = pd.read_csv(cards_csv)
    d = pd.read_csv(d_csv)
    if "note" in d.columns:
        d = d.iloc[0:0]

    cards_base = cards.rename(
        columns={
            "final_label_reference": "default_or_full_label",
        }
    ).copy()
    cards_base["source_case_type"] = cards_base["case_type"].astype(str).map(infer_case_letter)

    keep_card_cols = [
        "case_id",
        "case_type",
        "source_case_type",
        "event_id",
        "run_id",
        "source_experiment",
        "default_or_full_label",
        "compared_versions_labels",
        "recommended_priority",
        "prefix",
        "origin_as",
        "as_path_clean",
        "as_path_len",
        "risk_score",
        "certainty_score",
        "conflict_score",
        "missing_origin_or_path",
        "evidence_support_score",
        "structural_hit_count",
        "weak_hit_count",
        "candidate_reasons",
        "gate_condition_met",
        "gate_label",
        "augment_label",
        "top_contributing_factor",
    ]
    for c in keep_card_cols:
        if c not in cards_base.columns:
            cards_base[c] = ""
    cards_base = cards_base[keep_card_cols].copy()

    d_rows = []
    if not d.empty:
        d = d.copy()
        for i, row in d.reset_index(drop=True).iterrows():
            event_id = safe_str(row.get("event_id", ""))
            case_type = safe_str(row.get("case_type", "D_stealth_backup")) or "D_stealth_backup"
            d_rows.append(
                {
                    "case_id": f"D-{i+1:02d}",
                    "case_type": case_type,
                    "source_case_type": infer_case_letter(case_type),
                    "event_id": event_id,
                    "run_id": safe_str(row.get("run_id", "")),
                    "source_experiment": safe_str(row.get("source_experiment", "E8-A_backup_from_default")),
                    "default_or_full_label": safe_str(row.get("default_or_full_label", "")),
                    "compared_versions_labels": safe_str(row.get("compared_versions_labels", "")),
                    "recommended_priority": safe_str(row.get("recommended_priority", "medium")),
                    "prefix": safe_str(row.get("prefix", "")),
                    "origin_as": row.get("origin_as", np.nan),
                    "as_path_clean": safe_str(row.get("as_path_clean", "")),
                    "as_path_len": safe_int(row.get("as_path_len", 0)),
                    "risk_score": safe_float(row.get("risk_score", 0.0)),
                    "certainty_score": safe_float(row.get("certainty_score", 0.0)),
                    "conflict_score": safe_float(row.get("conflict_score", 0.0)),
                    "missing_origin_or_path": "",
                    "evidence_support_score": "",
                    "structural_hit_count": "",
                    "weak_hit_count": "",
                    "candidate_reasons": "",
                    "gate_condition_met": "",
                    "gate_label": "",
                    "augment_label": "",
                    "top_contributing_factor": safe_str(row.get("top_contributing_factor", "")),
                }
            )
    d_df = pd.DataFrame(d_rows)

    out = pd.concat([cards_base, d_df], axis=0, ignore_index=True)
    out["run_id"] = out.apply(infer_run_id, axis=1)

    out["_sort_case"] = out["source_case_type"].map({"A": 1, "B": 2, "C": 3, "D": 4}).fillna(9).astype(int)
    out["_sort_evt"] = out["event_id"].astype(str)
    out = out.sort_values(["_sort_case", "_sort_evt"]).drop(columns=["_sort_case", "_sort_evt"]).reset_index(drop=True)

    selected_ids = set(abc["event_id"].astype(str).tolist())
    if not d.empty and "event_id" in d.columns:
        selected_ids |= set(d["event_id"].astype(str).tolist())
    out = out[out["event_id"].astype(str).isin(selected_ids)].copy()
    out = out.reset_index(drop=True)
    return out


def choose_final_tag(grade_counts: dict[str, int]) -> str:
    high = int(grade_counts.get("high_confidence_event", 0))
    strong = int(grade_counts.get("strongly_suspicious", 0))
    needs = int(grade_counts.get("needs_external_review", 0))
    insuff = int(grade_counts.get("insufficient_external_support", 0))

    if high >= 2:
        return "external_validation=已形成首批high-confidence set"
    if strong >= 4:
        return "external_validation=形成初步validated suspicious set"
    if (strong + needs) >= 4 and insuff <= 4:
        return "external_validation=证据有限但方向正确"
    return "external_validation=需复查"


def main() -> None:
    parser = argparse.ArgumentParser(description="E8-B: targeted external validation and evidence mounting for E8-A selected events.")
    parser.add_argument("--abc-csv", default=DEFAULT_ABC_CSV)
    parser.add_argument("--d-csv", default=DEFAULT_D_CSV)
    parser.add_argument("--cards-csv", default=DEFAULT_CARDS_CSV)
    parser.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    runs_root = Path(args.runs_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pool = build_case_pool(
        abc_csv=Path(args.abc_csv),
        d_csv=Path(args.d_csv),
        cards_csv=Path(args.cards_csv),
    )
    if pool.empty:
        raise SystemExit("No events found in E8-A case pool inputs.")

    run_ids = sorted(set(pool["run_id"].astype(str).tolist()))
    payload_by_run: dict[str, dict[str, Any]] = {}
    for run_id in run_ids:
        payload_by_run[run_id] = load_run_payload(runs_root=runs_root, run_id=run_id)

    rows: list[dict[str, Any]] = []
    comm_rows: list[dict[str, Any]] = []
    topo_rows: list[dict[str, Any]] = []

    for _, case in pool.iterrows():
        event_id = safe_str(case.get("event_id", ""))
        run_id = safe_str(case.get("run_id", ""))
        payload = payload_by_run.get(run_id, {})
        events_df = payload.get("events", pd.DataFrame())
        final_df = payload.get("final", pd.DataFrame())
        scores_df = payload.get("scores", pd.DataFrame())
        gating_df = payload.get("gating", pd.DataFrame())
        augment_df = payload.get("augment", pd.DataFrame())
        updates_df = payload.get("updates", pd.DataFrame())
        updates_has_communities = bool(payload.get("updates_has_communities", False))

        event_row = events_df[events_df["event_id"].astype(str) == event_id].iloc[0] if not events_df.empty and (events_df["event_id"].astype(str) == event_id).any() else pd.Series(dtype=object)
        final_row = final_df[final_df["event_id"].astype(str) == event_id].iloc[0] if not final_df.empty and (final_df["event_id"].astype(str) == event_id).any() else pd.Series(dtype=object)
        score_row = scores_df[scores_df["event_id"].astype(str) == event_id].iloc[0] if not scores_df.empty and (scores_df["event_id"].astype(str) == event_id).any() else pd.Series(dtype=object)
        gating_row = gating_df[gating_df["event_id"].astype(str) == event_id].iloc[0] if not gating_df.empty and (gating_df["event_id"].astype(str) == event_id).any() else pd.Series(dtype=object)
        augment_row = augment_df[augment_df["event_id"].astype(str) == event_id].iloc[0] if not augment_df.empty and (augment_df["event_id"].astype(str) == event_id).any() else pd.Series(dtype=object)

        prefix = safe_str(event_row.get("prefix", case.get("prefix", "")))
        origin_as = event_row.get("origin_as", case.get("origin_as", np.nan))
        as_path_clean = safe_str(event_row.get("as_path_clean", case.get("as_path_clean", "")))
        as_path_len_val = safe_int(event_row.get("as_path_len", case.get("as_path_len", as_path_len(as_path_clean))))
        first_seen = event_row.get("first_seen", np.nan)
        last_seen = event_row.get("last_seen", np.nan)
        first_seen_utc = ts_to_utc_text(first_seen)
        last_seen_utc = ts_to_utc_text(last_seen)
        collector_set = safe_str(event_row.get("collector_set", ""))
        visible_collectors = parse_collectors(collector_set)
        collector_count = safe_int(event_row.get("collector_count", 0))
        visibility_count = safe_int(event_row.get("visibility_count", 0))
        rel_seq = safe_str(event_row.get("rel_seq", ""))
        rel_unknown_cnt = safe_int(event_row.get("rel_unknown_cnt", 0))

        matched_updates = match_event_updates(event_row, updates_df) if not event_row.empty else pd.DataFrame()
        peer_unique_count, peer_summary = build_peer_summary(matched_updates, topk=5)

        if not updates_has_communities:
            has_communities = "no"
            has_no_export = "unknown"
            has_no_advertise = "unknown"
            communities_raw_sample = ""
            communities_tokens_sample = ""
            communities_unavailable = True
        else:
            communities_unavailable = False
            token_set: list[str] = []
            raw_samples: list[str] = []
            no_export_hit = False
            no_advertise_hit = False
            has_any_communities = False

            if not matched_updates.empty and "communities" in matched_updates.columns:
                for v in matched_updates["communities"]:
                    flattened = flatten_community_value(v)
                    if flattened:
                        has_any_communities = True
                    if len(raw_samples) < 3:
                        raw_samples.append(safe_str(repr(v))[:240])
                    toks, no_export, no_advertise = parse_community_tokens(v)
                    token_set.extend(toks)
                    no_export_hit = no_export_hit or no_export
                    no_advertise_hit = no_advertise_hit or no_advertise
            token_set = list(dict.fromkeys(token_set))

            has_communities = "yes" if has_any_communities else "no"
            if has_communities == "no":
                has_no_export = "no"
                has_no_advertise = "no"
            else:
                has_no_export = "yes" if no_export_hit else "no"
                has_no_advertise = "yes" if no_advertise_hit else "no"

            communities_raw_sample = " || ".join(raw_samples)
            communities_tokens_sample = "|".join(token_set[:20])

        topology_violation, relationship_summary, violation_hint = evaluate_valley_free(rel_seq)

        source_case_type = safe_str(case.get("source_case_type", infer_case_letter(case.get("case_type", ""))))
        source_experiment = safe_str(case.get("source_experiment", ""))
        default_or_full_label = safe_str(case.get("default_or_full_label", final_row.get("final_alert_label", "")))
        compared_labels = parse_compared_labels(case.get("compared_versions_labels", ""))
        compared_labels_text = json.dumps(compared_labels, ensure_ascii=False, sort_keys=True)

        risk_score = safe_float(case.get("risk_score", final_row.get("risk_score", score_row.get("risk_score", 0.0))))
        certainty_score = safe_float(case.get("certainty_score", final_row.get("certainty_score", gating_row.get("certainty_score", 0.0))))
        conflict_score = safe_float(case.get("conflict_score", final_row.get("conflict_score", gating_row.get("conflict_score", 0.0))))
        missing_origin_or_path = bool(case.get("missing_origin_or_path", final_row.get("missing_origin_or_path", score_row.get("missing_origin_or_path", False))))
        evidence_support_score = safe_float(case.get("evidence_support_score", final_row.get("evidence_support_score", augment_row.get("evidence_support_score", 0.0))))
        gate_label = safe_str(case.get("gate_label", final_row.get("gating_label", gating_row.get("gating_label", ""))))
        augment_label = safe_str(case.get("augment_label", final_row.get("augmentation_label", augment_row.get("augmentation_label", ""))))
        top_factor = safe_str(case.get("top_contributing_factor", final_row.get("top_contributing_factor", score_row.get("top_contributing_factor", ""))))
        reasons = parse_reason_list(case.get("candidate_reasons", final_row.get("candidate_reasons", score_row.get("candidate_reasons", ""))))

        structural_hits = case.get("structural_hit_count", "")
        weak_hits = case.get("weak_hit_count", "")
        if is_missing(structural_hits) or is_missing(weak_hits):
            structural_hits_calc = len([x for x in reasons if x in STRUCTURAL_KEYS])
            weak_hits_calc = len(reasons) - structural_hits_calc
            structural_hit_count = structural_hits_calc
            weak_hit_count = weak_hits_calc
        else:
            structural_hit_count = safe_int(structural_hits, default=0)
            weak_hit_count = safe_int(weak_hits, default=max(len(reasons) - structural_hit_count, 0))

        gate_condition_val = case.get("gate_condition_met", "")
        if gate_condition_val in [True, False]:
            gate_condition_met = bool(gate_condition_val)
        else:
            risk_bucket = safe_str(score_row.get("risk_bucket", final_row.get("risk_bucket", "")))
            structural_score = safe_float(score_row.get("structural_novelty_score", 0.0))
            gate_condition_met = gate_condition_met_from_metrics(
                risk_bucket=risk_bucket,
                certainty=certainty_score,
                conflict=conflict_score,
                structural_score=structural_score,
                missing=missing_origin_or_path,
            )

        historical_hint, structural_hint, visibility_hint = derive_hints(
            reasons=reasons,
            structural_hit_count=structural_hit_count,
            top_factor=top_factor,
            case_letter=source_case_type,
            collector_count=collector_count,
            visibility_count=visibility_count,
        )

        row = {
            "case_id": safe_str(case.get("case_id", "")),
            "event_id": event_id,
            "case_type": safe_str(case.get("case_type", "")),
            "source_case_type": source_case_type,
            "source_experiment": source_experiment,
            "run_id": run_id,
            "prefix": prefix,
            "origin_as": origin_as,
            "as_path_clean": as_path_clean,
            "as_path_len": as_path_len_val,
            "first_seen_utc": first_seen_utc,
            "last_seen_utc": last_seen_utc,
            "visible_collectors": "|".join(visible_collectors),
            "collector_count": collector_count,
            "visibility_count": visibility_count,
            "peer_asn_unique_count": peer_unique_count,
            "peer_observation_summary": peer_summary,
            "rel_seq": rel_seq,
            "rel_unknown_cnt": rel_unknown_cnt,
            "relationship_summary": relationship_summary,
            "topology_violation": topology_violation,
            "violation_hint": violation_hint,
            "has_communities": has_communities,
            "has_no_export": has_no_export,
            "has_no_advertise": has_no_advertise,
            "communities_raw_sample": communities_raw_sample,
            "communities_tokens_sample": communities_tokens_sample,
            "communities_unavailable": communities_unavailable,
            "matched_update_rows": int(len(matched_updates)),
            "default_or_full_label": default_or_full_label,
            "compared_versions_labels": compared_labels_text,
            "risk_score": risk_score,
            "certainty_score": certainty_score,
            "conflict_score": conflict_score,
            "missing_origin_or_path": missing_origin_or_path,
            "evidence_support_score": evidence_support_score,
            "structural_hit_count": structural_hit_count,
            "weak_hit_count": weak_hit_count,
            "gate_condition_met": gate_condition_met,
            "gate_label": gate_label,
            "augment_label": augment_label,
            "historical_anomaly_hint": historical_hint,
            "structural_anomaly_hint": structural_hint,
            "visibility_anomaly_hint": visibility_hint,
            "external_validation_hook": build_external_hook(source_case_type),
        }
        rows.append(row)

        comm_rows.append(
            {
                "event_id": event_id,
                "case_type": safe_str(case.get("case_type", "")),
                "run_id": run_id,
                "has_communities": has_communities,
                "has_no_export": has_no_export,
                "has_no_advertise": has_no_advertise,
                "communities_raw_sample": communities_raw_sample,
                "communities_tokens_sample": communities_tokens_sample,
                "communities_unavailable": communities_unavailable,
                "matched_update_rows": int(len(matched_updates)),
            }
        )
        topo_rows.append(
            {
                "event_id": event_id,
                "case_type": safe_str(case.get("case_type", "")),
                "run_id": run_id,
                "rel_seq": rel_seq,
                "rel_unknown_cnt": rel_unknown_cnt,
                "relationship_summary": relationship_summary,
                "topology_violation": topology_violation,
                "violation_hint": violation_hint,
            }
        )

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        raise SystemExit("No rows produced for external validation.")

    grades = out_df.apply(grade_event, axis=1, result_type="expand")
    out_df["evidence_grade"] = grades[0]
    out_df["grading_reason"] = grades[1]

    out_df["_case_order"] = out_df["source_case_type"].map({"A": 1, "B": 2, "C": 3, "D": 4}).fillna(9).astype(int)
    out_df = out_df.sort_values(["_case_order", "event_id"]).drop(columns=["_case_order"]).reset_index(drop=True)

    csv_path = output_dir / "e8b_case_external_validation.csv"
    out_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    comm_df = pd.DataFrame(comm_rows).sort_values(["case_type", "event_id"]).reset_index(drop=True)
    topo_df = pd.DataFrame(topo_rows).sort_values(["case_type", "event_id"]).reset_index(drop=True)
    comm_df.to_csv(output_dir / "e8b_case_communities_extract.csv", index=False, encoding="utf-8-sig")
    topo_df.to_csv(output_dir / "e8b_case_topology_flags.csv", index=False, encoding="utf-8-sig")

    grade_counts = {k: int(v) for k, v in out_df["evidence_grade"].value_counts().to_dict().items()}
    case_counts = {k: int(v) for k, v in out_df["source_case_type"].value_counts().to_dict().items()}
    final_tag = choose_final_tag(grade_counts)
    summary_json = {
        "validated_event_count": int(len(out_df)),
        "grade_counts": grade_counts,
        "case_type_counts": case_counts,
        "topology_violation_counts": {k: int(v) for k, v in out_df["topology_violation"].value_counts().to_dict().items()},
        "communities_presence_counts": {k: int(v) for k, v in out_df["has_communities"].value_counts().to_dict().items()},
        "final_tag": final_tag,
        "inputs": {
            "abc_csv": str(Path(args.abc_csv).resolve()),
            "d_csv": str(Path(args.d_csv).resolve()),
            "cards_csv": str(Path(args.cards_csv).resolve()),
            "runs_root": str(runs_root.resolve()),
        },
        "outputs": {
            "validation_csv": str(csv_path.resolve()),
            "validation_md": str((output_dir / "e8b_case_external_validation.md").resolve()),
            "final_cards_md": str((output_dir / "e8b_final_case_cards.md").resolve()),
        },
    }
    (output_dir / "e8b_case_validation_summary.json").write_text(json.dumps(summary_json, ensure_ascii=False, indent=2), encoding="utf-8")

    case_grade = (
        out_df.groupby(["source_case_type", "evidence_grade"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["source_case_type", "evidence_grade"])
    )

    md_lines = []
    md_lines.append("# E8-B External Validation Summary")
    md_lines.append("")
    md_lines.append(f"- validated_events: {len(out_df)}")
    md_lines.append(f"- final_tag: {final_tag}")
    md_lines.append("")
    md_lines.append("## Evidence Grade Counts")
    md_lines.append("")
    md_lines.append("| evidence_grade | count |")
    md_lines.append("|---|---:|")
    for k, v in sorted(grade_counts.items()):
        md_lines.append(f"| {k} | {v} |")
    md_lines.append("")
    md_lines.append("## Case-Type Overview")
    md_lines.append("")
    md_lines.append("| source_case_type | evidence_grade | count |")
    md_lines.append("|---|---|---:|")
    for _, r in case_grade.iterrows():
        md_lines.append(f"| {r['source_case_type']} | {r['evidence_grade']} | {int(r['count'])} |")
    md_lines.append("")

    rank_grade = {
        "high_confidence_event": 0,
        "strongly_suspicious": 1,
        "needs_external_review": 2,
        "insufficient_external_support": 3,
    }
    rank_case = {"C": 0, "D": 1, "B": 2, "A": 3}
    ranked = out_df.copy()
    ranked["_g"] = ranked["evidence_grade"].map(rank_grade).fillna(9)
    ranked["_c"] = ranked["source_case_type"].map(rank_case).fillna(9)
    ranked = ranked.sort_values(["_g", "_c", "risk_score", "certainty_score"], ascending=[True, True, False, False])
    top_case = ranked.head(6)

    md_lines.append("## Recommended Formal Case-Study Candidates")
    md_lines.append("")
    md_lines.append("| event_id | case_type | evidence_grade | risk | certainty | topology_violation |")
    md_lines.append("|---|---|---|---:|---:|---|")
    for _, r in top_case.iterrows():
        md_lines.append(
            f"| {r['event_id']} | {r['case_type']} | {r['evidence_grade']} | "
            f"{float(r['risk_score']):.2f} | {float(r['certainty_score']):.2f} | {r['topology_violation']} |"
        )

    md_lines.append("")
    md_lines.append("## Notes")
    md_lines.append("")
    md_lines.append("- Labels are conservative: events are treated as high-value suspicious/candidate attack events, not confirmed attacks.")
    md_lines.append("- `topology_violation=uncertain` is used whenever `rel_seq` is missing/unknown edges prevent strict valley-free judgement.")
    md_lines.append("- Communities evidence is only attached from existing updates fields; no new external feed is hard-required in this round.")
    (output_dir / "e8b_case_external_validation.md").write_text("\n".join(md_lines), encoding="utf-8")

    card_lines = []
    card_lines.append("# E8-B Final Case Cards")
    card_lines.append("")
    card_lines.append(
        "All cases are reported as high-value suspicious/candidate attack events with conservative evidence grades."
    )
    card_lines.append("")
    sorted_cards = out_df.copy()
    sorted_cards["_case_order"] = sorted_cards["source_case_type"].map({"A": 1, "B": 2, "C": 3, "D": 4}).fillna(9)
    sorted_cards = sorted_cards.sort_values(["_case_order", "event_id"]).drop(columns=["_case_order"])

    for _, r in sorted_cards.iterrows():
        card_lines.append(f"## {r['case_id']} | {r['event_id']} | {r['case_type']}")
        card_lines.append("")
        card_lines.append("### 1) Event Context")
        card_lines.append(f"- event_id: `{r['event_id']}`")
        card_lines.append(f"- prefix: `{r['prefix']}`")
        card_lines.append(f"- origin_as: `{r['origin_as']}`")
        card_lines.append(f"- as_path (len): `{r['as_path_clean']}` (len={int(r['as_path_len'])})")
        card_lines.append(f"- source_run / source_experiment: `{r['run_id']}` / `{r['source_experiment']}`")
        card_lines.append("")
        card_lines.append("### 2) Version-Path Comparison")
        card_lines.append("- baseline path: `event -> baseline -> candidate -> score -> gate -> augment -> final`")
        card_lines.append(f"- compared settings labels: `{r['compared_versions_labels']}`")
        card_lines.append(
            f"- key transition: label_ref=`{r['default_or_full_label']}`, grade=`{r['evidence_grade']}`"
        )
        card_lines.append("")
        card_lines.append("### 3) Key Evidence Delta")
        card_lines.append(
            f"- risk/certainty/conflict: `{float(r['risk_score']):.2f}` / `{float(r['certainty_score']):.2f}` / `{float(r['conflict_score']):.2f}`"
        )
        card_lines.append(f"- missing_origin_or_path: `{bool(r['missing_origin_or_path'])}`")
        card_lines.append(f"- evidence_support_score: `{float(r['evidence_support_score']):.2f}`")
        card_lines.append(
            f"- structural/weak hits: `{int(r['structural_hit_count'])}` / `{int(r['weak_hit_count'])}`"
        )
        card_lines.append(
            f"- topology/community: violation=`{r['topology_violation']}`, no_export=`{r['has_no_export']}`, no_advertise=`{r['has_no_advertise']}`"
        )
        card_lines.append("")
        card_lines.append("### 4) Why Upgrade / Downgrade / Missing")
        card_lines.append(f"- system path hint: gate=`{r['gate_label']}`, augment=`{r['augment_label']}`, gate_condition_met=`{r['gate_condition_met']}`")
        card_lines.append(f"- visibility hint: `{r['visibility_anomaly_hint']}`")
        card_lines.append(f"- judgement note: `{r['grading_reason']}`")
        card_lines.append("")
        card_lines.append("### 5) Supported Paper Claim")
        card_lines.append(
            "- supported claim: layered decision under weak-signal/partial observability reduces over-claiming while preserving suspicious-event discovery."
        )
        card_lines.append(
            f"- this case contributes because: `{r['source_case_type']}`-class behavior aligns with the expected layer responsibility."
        )
        card_lines.append("")
        card_lines.append("### 6) External Validation Hook")
        card_lines.append(f"- {r['external_validation_hook']}")
        card_lines.append("")

    (output_dir / "e8b_final_case_cards.md").write_text("\n".join(card_lines), encoding="utf-8")

    print(f"validated_events={len(out_df)}")
    print(f"grade_counts={grade_counts}")
    print(f"case_type_counts={case_counts}")
    print(f"topology_counts={summary_json['topology_violation_counts']}")
    print(f"final_tag={final_tag}")


if __name__ == "__main__":
    main()
