import argparse
import ast
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_E6B1_PARQUET = "outputs/e6b1_nogate_ablation_v02/e6b1_no_gate_final_alerts.parquet"
DEFAULT_E6B2_PARQUET = "outputs/e6b2_noaugment_ablation_v01/e6b2_no_augment_final_alerts.parquet"
DEFAULT_E6B3_PARQUET = "outputs/e6b3_joint_ablation_v01/e6b3_four_setting_final_alerts.parquet"
DEFAULT_E7B_SAMPLES_CSV = "outputs/e7b_collector_structure_v01/e7b_asymmetric_full_high_samples.csv"
DEFAULT_E7A_SETTINGS_CSV = "outputs/e7a_visibility_ablation_v01/e7a_settings_registry.csv"
DEFAULT_OUTPUT_DIR = "outputs/e8a_case_pool_v01"

# Keep in sync with gate logic.
CERTAINTY_THRESHOLD_HIGH = 65.0
CONFLICT_THRESHOLD_HIGH = 35.0
STRUCTURAL_MIN_FOR_HIGH = 45.0

STRUCTURAL_REASON_KEYS = {
    "unseen_origin_for_prefix",
    "unseen_path_for_prefix_origin",
}


def to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def to_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def as_path_len(path_val: Any) -> int:
    text = str(path_val or "").strip()
    if not text:
        return 0
    return len([x for x in text.split(" ") if x.strip()])


def parse_reasons(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    text = str(val).strip()
    if not text:
        return []
    for fn in (json.loads, ast.literal_eval):
        try:
            parsed = fn(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    # Fallback for non-standard formatting.
    text = text.strip("[]")
    parts = [p.strip().strip("'").strip('"') for p in text.split(",")]
    return [p for p in parts if p]


def split_reason_groups(reasons: list[str]) -> tuple[list[str], list[str]]:
    structural = [x for x in reasons if x in STRUCTURAL_REASON_KEYS]
    weak = [x for x in reasons if x not in STRUCTURAL_REASON_KEYS]
    return structural, weak


def gate_high_pass(df: pd.DataFrame) -> pd.Series:
    risk_bucket_high = df.get("risk_bucket", "").fillna("").astype(str).eq("high")
    certainty_ok = to_num(df.get("certainty_score", 0.0)) >= CERTAINTY_THRESHOLD_HIGH
    conflict_ok = to_num(df.get("conflict_score", 0.0)) < CONFLICT_THRESHOLD_HIGH
    structural_ok = to_num(df.get("structural_novelty_score", 0.0)) >= STRUCTURAL_MIN_FOR_HIGH
    missing_ok = ~to_bool(df.get("missing_origin_or_path", False))
    return risk_bucket_high & certainty_ok & conflict_ok & structural_ok & missing_ok


def label_compact(text: Any) -> str:
    val = str(text or "").strip()
    return val if val else "missing"


def load_optional_run_payload(runs_root: Path, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    run_dir = runs_root / run_id
    if not run_dir.exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    final_p = run_dir / "final" / "final_alerts.parquet"
    events_p = run_dir / "events" / "event_units.parquet"
    scores_p = run_dir / "scores" / "scored_candidates.parquet"
    if not final_p.exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    final_df = pd.read_parquet(final_p)
    events_df = pd.read_parquet(events_p) if events_p.exists() else pd.DataFrame()
    scores_df = pd.read_parquet(scores_p) if scores_p.exists() else pd.DataFrame()
    return final_df, events_df, scores_df


def base_card_fields(
    *,
    case_id: str,
    case_type: str,
    priority: str,
    source_experiment: str,
    run_id: str,
    event_id: str,
    prefix: Any,
    origin_as: Any,
    as_path_clean: Any,
    candidate_status: str,
    risk_score: Any,
    certainty_score: Any,
    conflict_score: Any,
    gate_label: Any,
    gate_condition_met: Any,
    augment_label: Any,
    final_label_reference: Any,
    compared_versions_labels: dict[str, Any],
    transition_note: str,
    candidate_reasons: Any,
    missing_origin_or_path: Any,
    evidence_support_score: Any,
    top_contributing_factor: Any,
) -> dict[str, Any]:
    reason_list = parse_reasons(candidate_reasons)
    structural_reasons, weak_reasons = split_reason_groups(reason_list)
    clean_path = str(as_path_clean or "")
    return {
        "case_id": case_id,
        "case_type": case_type,
        "recommended_priority": priority,
        "source_experiment": source_experiment,
        "run_id": str(run_id),
        "event_id": str(event_id),
        "prefix": str(prefix or ""),
        "origin_as": origin_as,
        "as_path_clean": clean_path,
        "as_path_len": int(as_path_len(clean_path)),
        "candidate_status": candidate_status,
        "risk_score": float(pd.to_numeric(pd.Series([risk_score]), errors="coerce").fillna(0.0).iloc[0]),
        "certainty_score": float(pd.to_numeric(pd.Series([certainty_score]), errors="coerce").fillna(0.0).iloc[0]),
        "conflict_score": float(pd.to_numeric(pd.Series([conflict_score]), errors="coerce").fillna(0.0).iloc[0]),
        "gate_label": str(gate_label or ""),
        "gate_condition_met": bool(gate_condition_met) if gate_condition_met in (True, False) else "",
        "augment_label": str(augment_label or ""),
        "final_label_reference": str(final_label_reference or ""),
        "compared_versions_labels": json.dumps(compared_versions_labels, ensure_ascii=False, sort_keys=True),
        "transition_note": transition_note,
        "candidate_reasons": json.dumps(reason_list, ensure_ascii=False),
        "structural_hit_count": int(len(structural_reasons)),
        "weak_hit_count": int(len(weak_reasons)),
        "structural_reasons": json.dumps(structural_reasons, ensure_ascii=False),
        "weak_reasons": json.dumps(weak_reasons, ensure_ascii=False),
        "missing_origin_or_path": bool(missing_origin_or_path) if missing_origin_or_path in (True, False) else "",
        "evidence_support_score": float(pd.to_numeric(pd.Series([evidence_support_score]), errors="coerce").fillna(0.0).iloc[0]),
        "top_contributing_factor": str(top_contributing_factor or ""),
    }


def build_template_markdown() -> str:
    return (
        "# E8 Case Template (Unified)\n\n"
        "## 1) Event Context\n"
        "- event_id:\n"
        "- prefix:\n"
        "- origin_as:\n"
        "- as_path (and len):\n"
        "- source_run / source_experiment:\n\n"
        "## 2) Version-Path Comparison\n"
        "- baseline path: default(full) -> candidate -> score -> gate -> augment -> final\n"
        "- compared settings labels:\n"
        "- key transition (retain / downgrade / missing):\n\n"
        "## 3) Key Evidence Delta\n"
        "- risk_score:\n"
        "- certainty_score:\n"
        "- conflict_score:\n"
        "- missing_origin_or_path:\n"
        "- evidence_support_score:\n"
        "- structural vs weak reasons:\n\n"
        "## 4) Why Upgrade / Downgrade / Missing\n"
        "- what changed in this setting:\n"
        "- direct mechanism:\n"
        "- why final label changed:\n\n"
        "## 5) Supported Paper Claim\n"
        "- claim line (layered responsibility / partial observability / conservative degradation):\n"
        "- this case contributes because:\n\n"
        "## 6) External Validation Hook\n"
        "- one-sentence external validation plan placeholder (RPKI/ROA, operator incident report, public outage timeline, or IRR consistency cross-check):\n"
    )


def choose_a_cases(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    pool = df[
        (df["default_final_alert_label"].fillna("").astype(str) != "high_priority_alert")
        & (df["no_gate_final_alert_label"].fillna("").astype(str) == "high_priority_alert")
    ].copy()
    if pool.empty:
        return pool
    pool["gate_condition_met"] = gate_high_pass(pool)
    pool["as_path_len"] = pool.get("as_path_clean", "").fillna("").astype(str).map(as_path_len)
    pool["_path_pref"] = (pool["as_path_len"] <= 6).astype(int)
    pool = pool.sort_values(
        [
            "missing_origin_or_path",
            "conflict_score",
            "gate_condition_met",
            "certainty_score",
            "_path_pref",
            "as_path_len",
            "risk_score",
        ],
        ascending=[False, False, True, True, False, True, False],
    )
    return pool.head(limit).copy()


def choose_b_cases(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    df = df.copy()
    df["as_path_len"] = df.get("as_path_clean", "").fillna("").astype(str).map(as_path_len)
    df["_path_pref"] = (df["as_path_len"] <= 6).astype(int)

    primary = df[
        (df["default_final_alert_label"].fillna("").astype(str) == "high_priority_alert")
        & (df["no_augment_final_alert_label"].fillna("").astype(str) == "needs_review")
    ].copy()
    secondary = df[
        (df["default_final_alert_label"].fillna("").astype(str) == "low_priority_or_background")
        & (df["no_augment_final_alert_label"].fillna("").astype(str) == "needs_review")
    ].copy()

    primary = primary.sort_values(
        ["_path_pref", "evidence_support_score", "risk_score", "certainty_score"],
        ascending=[False, False, False, False],
    )
    secondary = secondary.sort_values(
        ["_path_pref", "evidence_support_score", "risk_score", "certainty_score"],
        ascending=[False, False, False, False],
    )

    picked_frames: list[pd.DataFrame] = []
    if not primary.empty:
        picked_frames.append(primary.head(min(limit, len(primary))))
    picked_count = sum(len(x) for x in picked_frames)
    if picked_count < limit and not secondary.empty:
        picked_frames.append(secondary.head(limit - picked_count))

    if picked_count + (len(picked_frames[-1]) if picked_frames else 0) < limit:
        fallback = df[
            (df["default_final_alert_label"].fillna("").astype(str) == "needs_review")
            & (df["no_augment_final_alert_label"].fillna("").astype(str) == "low_priority_or_background")
        ].copy()
        fallback = fallback.sort_values(
            ["_path_pref", "risk_score", "certainty_score"],
            ascending=[False, False, False],
        )
        need = limit - sum(len(x) for x in picked_frames)
        if need > 0 and not fallback.empty:
            picked_frames.append(fallback.head(need))

    if not picked_frames:
        return pd.DataFrame(columns=df.columns)
    out = pd.concat(picked_frames, axis=0, ignore_index=True).drop_duplicates("event_id")
    return out.head(limit).copy()


def choose_c_cases(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    if df.empty:
        return df
    status_cols = [c for c in df.columns if c.endswith("_status")]
    if len(status_cols) < 2:
        return df.head(limit).copy()
    a_col, b_col = status_cols[0], status_cols[1]
    out_parts: list[pd.DataFrame] = []

    p1 = df[(df[a_col].fillna("missing") == "missing") & (df[b_col].fillna("missing") != "missing")].copy()
    p2 = df[(df[b_col].fillna("missing") == "missing") & (df[a_col].fillna("missing") != "missing")].copy()
    rest = df.copy()

    for part in (p1, p2):
        if part.empty:
            continue
        part["as_path_len"] = part.get("as_path_clean", "").fillna("").astype(str).map(as_path_len)
        part["_path_pref"] = (part["as_path_len"] <= 6).astype(int)
        part = part.sort_values(
            ["_path_pref", "full_risk_score", "full_certainty_score"],
            ascending=[False, False, False],
        )
        out_parts.append(part.head(1))
        rest = rest[~rest["signature"].isin(part.head(1)["signature"])]

    if sum(len(x) for x in out_parts) < limit:
        rest = rest.copy()
        rest["as_path_len"] = rest.get("as_path_clean", "").fillna("").astype(str).map(as_path_len)
        rest["_path_pref"] = (rest["as_path_len"] <= 6).astype(int)
        rest = rest.sort_values(
            ["_path_pref", "full_risk_score", "full_certainty_score"],
            ascending=[False, False, False],
        )
        need = limit - sum(len(x) for x in out_parts)
        out_parts.append(rest.head(need))

    return pd.concat(out_parts, axis=0, ignore_index=True).head(limit).copy()


def build_cards(
    a_cases: pd.DataFrame,
    b_cases: pd.DataFrame,
    c_cases: pd.DataFrame,
    e6b3_map: pd.DataFrame,
    e7a_settings: pd.DataFrame,
    runs_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cards: list[dict[str, Any]] = []

    # A cards.
    for idx, row in a_cases.reset_index(drop=True).iterrows():
        event_id = str(row.get("event_id", ""))
        m = e6b3_map[e6b3_map["event_id"].astype(str) == event_id]
        mrow = m.iloc[0] if len(m) else row
        labels = {
            "default": label_compact(mrow.get("default_final_alert_label", "")),
            "no_gate": label_compact(mrow.get("no_gate_final_alert_label", "")),
            "no_augment": label_compact(mrow.get("no_augment_final_alert_label", "")),
            "no_gate_no_augment": label_compact(mrow.get("no_gate_no_augment_final_alert_label", "")),
        }
        cards.append(
            base_card_fields(
                case_id=f"A-{idx + 1:02d}",
                case_type="A_gate_upfloat_block",
                priority="high",
                source_experiment="E6-B-1",
                run_id=str(row.get("run_id", "")),
                event_id=event_id,
                prefix=row.get("prefix", ""),
                origin_as=row.get("origin_as", None),
                as_path_clean=row.get("as_path_clean", ""),
                candidate_status="candidate_selected",
                risk_score=row.get("risk_score", 0.0),
                certainty_score=row.get("certainty_score", 0.0),
                conflict_score=row.get("conflict_score", 0.0),
                gate_label=row.get("gating_label", ""),
                gate_condition_met=row.get("gate_condition_met", ""),
                augment_label=row.get("augmentation_label", ""),
                final_label_reference=row.get("default_final_alert_label", ""),
                compared_versions_labels=labels,
                transition_note=(
                    f"default={labels['default']} -> no_gate={labels['no_gate']} "
                    f"(gate_condition_met={bool(row.get('gate_condition_met', False))})"
                ),
                candidate_reasons=row.get("candidate_reasons", ""),
                missing_origin_or_path=row.get("missing_origin_or_path", False),
                evidence_support_score=row.get("evidence_support_score", 0.0),
                top_contributing_factor=row.get("top_contributing_factor", ""),
            )
        )

    # B cards.
    for idx, row in b_cases.reset_index(drop=True).iterrows():
        event_id = str(row.get("event_id", ""))
        m = e6b3_map[e6b3_map["event_id"].astype(str) == event_id]
        mrow = m.iloc[0] if len(m) else row
        labels = {
            "default": label_compact(mrow.get("default_final_alert_label", "")),
            "no_gate": label_compact(mrow.get("no_gate_final_alert_label", "")),
            "no_augment": label_compact(mrow.get("no_augment_final_alert_label", "")),
            "no_gate_no_augment": label_compact(mrow.get("no_gate_no_augment_final_alert_label", "")),
        }
        transition_note = f"default={labels['default']} -> no_augment={labels['no_augment']}"
        priority = "high" if labels["default"] == "high_priority_alert" else "medium"
        cards.append(
            base_card_fields(
                case_id=f"B-{idx + 1:02d}",
                case_type="B_augment_boundary",
                priority=priority,
                source_experiment="E6-B-2",
                run_id=str(row.get("run_id", "")),
                event_id=event_id,
                prefix=row.get("prefix", ""),
                origin_as=row.get("origin_as", None),
                as_path_clean=row.get("as_path_clean", ""),
                candidate_status="candidate_selected",
                risk_score=row.get("risk_score", 0.0),
                certainty_score=row.get("certainty_score", 0.0),
                conflict_score=row.get("conflict_score", 0.0),
                gate_label=row.get("gating_label", ""),
                gate_condition_met=(
                    str(row.get("gating_label", "")) == "likely_malicious"
                    and str(row.get("no_augment_final_alert_label", "")) == "high_priority_alert"
                ),
                augment_label=row.get("augmentation_label", ""),
                final_label_reference=row.get("default_final_alert_label", ""),
                compared_versions_labels=labels,
                transition_note=transition_note,
                candidate_reasons=row.get("candidate_reasons", ""),
                missing_origin_or_path=row.get("missing_origin_or_path", False),
                evidence_support_score=row.get("evidence_support_score", 0.0),
                top_contributing_factor=row.get("top_contributing_factor", ""),
            )
        )

    # C cards.
    full_run_id = ""
    rv_run_id = ""
    rrc_run_id = ""
    if not e7a_settings.empty:
        full_sel = e7a_settings[e7a_settings["setting"].astype(str) == "full"]
        if len(full_sel):
            full_run_id = str(full_sel.iloc[0].get("run_id", ""))
        for _, r in e7a_settings.iterrows():
            c_name = str(r.get("selected_collectors", "")).strip()
            if c_name == "route-views.sg":
                rv_run_id = str(r.get("run_id", ""))
            if c_name == "rrc00":
                rrc_run_id = str(r.get("run_id", ""))

    full_final, _, _ = load_optional_run_payload(runs_root=runs_root, run_id=full_run_id) if full_run_id else (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    full_final_idx = full_final.set_index("event_id", drop=False) if not full_final.empty else pd.DataFrame()

    status_cols = [c for c in c_cases.columns if c.endswith("_status")]
    a_status_col = status_cols[0] if len(status_cols) >= 1 else ""
    b_status_col = status_cols[1] if len(status_cols) >= 2 else ""
    a_label_name = a_status_col[: -len("_status")] if a_status_col else "collector_a_only"
    b_label_name = b_status_col[: -len("_status")] if b_status_col else "collector_b_only"

    for idx, row in c_cases.reset_index(drop=True).iterrows():
        full_event_id = str(row.get("full_event_id", ""))
        full_info = full_final_idx.loc[full_event_id] if (not full_final.empty and full_event_id in full_final_idx.index) else None
        candidate_reasons = full_info.get("candidate_reasons", "") if full_info is not None else ""
        missing_flag = full_info.get("missing_origin_or_path", False) if full_info is not None else False
        evidence_support = full_info.get("evidence_support_score", 0.0) if full_info is not None else 0.0
        gate_label = full_info.get("gating_label", "") if full_info is not None else ""
        augment_label = full_info.get("augmentation_label", "") if full_info is not None else ""
        top_factor = full_info.get("top_contributing_factor", "") if full_info is not None else ""
        compared = {
            "full": "high_priority_alert",
            a_label_name: label_compact(row.get(a_status_col, "missing")),
            b_label_name: label_compact(row.get(b_status_col, "missing")),
        }
        cards.append(
            base_card_fields(
                case_id=f"C-{idx + 1:02d}",
                case_type="C_collector_asymmetry",
                priority="high",
                source_experiment="E7-B",
                run_id=full_run_id,
                event_id=full_event_id,
                prefix=row.get("prefix", ""),
                origin_as=row.get("origin_as", None),
                as_path_clean=row.get("as_path_clean", ""),
                candidate_status="candidate_selected_full",
                risk_score=row.get("full_risk_score", 0.0),
                certainty_score=row.get("full_certainty_score", 0.0),
                conflict_score=row.get("full_conflict_score", 0.0),
                gate_label=gate_label,
                gate_condition_met=(str(gate_label) == "likely_malicious") if gate_label != "" else "",
                augment_label=augment_label,
                final_label_reference="high_priority_alert",
                compared_versions_labels=compared,
                transition_note=(
                    f"full=high_priority_alert; {a_label_name}={compared[a_label_name]}; "
                    f"{b_label_name}={compared[b_label_name]}"
                ),
                candidate_reasons=candidate_reasons,
                missing_origin_or_path=missing_flag,
                evidence_support_score=evidence_support,
                top_contributing_factor=top_factor,
            )
        )

    cards_df = pd.DataFrame(cards)

    summary_cols = [
        "case_type",
        "event_id",
        "prefix",
        "source_experiment",
        "final_label_reference",
        "compared_versions_labels",
        "recommended_priority",
        "as_path_len",
    ]
    summary_df = cards_df[summary_cols].copy() if not cards_df.empty else pd.DataFrame(columns=summary_cols)
    summary_df = summary_df.rename(columns={"final_label_reference": "default_or_full_label"})
    return cards_df, summary_df


def build_d_pool(run_id: str, runs_root: Path, limit: int) -> pd.DataFrame:
    final_df, events_df, scores_df = load_optional_run_payload(runs_root=runs_root, run_id=run_id)
    if final_df.empty:
        return pd.DataFrame()
    df = final_df.copy()
    if not events_df.empty:
        keep_cols = [
            c
            for c in [
                "event_id",
                "collector_count",
                "visibility_count",
                "record_count",
                "collector_set",
                "prefix",
                "origin_as",
                "as_path_clean",
            ]
            if c in events_df.columns
        ]
        df = df.merge(events_df[keep_cols], on="event_id", how="left", suffixes=("", "_evt"))
    if not scores_df.empty:
        keep_cols = [c for c in ["event_id", "structural_novelty_score", "candidate_reasons"] if c in scores_df.columns]
        df = df.merge(scores_df[keep_cols], on="event_id", how="left", suffixes=("", "_score"))

    high = df[df["final_alert_label"].fillna("").astype(str) == "high_priority_alert"].copy()
    if high.empty:
        return pd.DataFrame()

    low_vis = (
        (to_num(high.get("collector_count", 0.0)) <= 1.0)
        | (to_num(high.get("visibility_count", 0.0)) <= 1.0)
    )
    high = high[low_vis].copy()
    if high.empty:
        return pd.DataFrame()

    # Strong structural abnormality preference.
    reasons = high.get("candidate_reasons", "").fillna("").astype(str)
    structural_reason = reasons.str.contains("unseen_origin_for_prefix|unseen_path_for_prefix_origin", regex=True, na=False)
    top_struct = high.get("top_contributing_factor", "").fillna("").astype(str).eq("structural_novelty_score")
    structural_score_hi = to_num(high.get("structural_novelty_score", 0.0)) >= 50.0
    high = high[structural_reason | top_struct | structural_score_hi].copy()
    if high.empty:
        return pd.DataFrame()

    high["as_path_len"] = high.get("as_path_clean", "").fillna("").astype(str).map(as_path_len)
    high["_path_pref"] = (high["as_path_len"] <= 6).astype(int)
    high = high.sort_values(
        ["_path_pref", "risk_score", "certainty_score", "structural_novelty_score"],
        ascending=[False, False, False, False],
    )

    out = high.head(limit).copy()
    out = out.assign(
        case_type="D_stealth_backup",
        recommended_priority="medium",
        source_experiment="E8-A_backup_from_default",
        default_or_full_label="high_priority_alert",
    )
    out["compared_versions_labels"] = out.apply(
        lambda r: json.dumps(
            {
                "default": "high_priority_alert",
                "collector_count": int(pd.to_numeric(pd.Series([r.get("collector_count", 0)]), errors="coerce").fillna(0).iloc[0]),
                "visibility_count": int(pd.to_numeric(pd.Series([r.get("visibility_count", 0)]), errors="coerce").fillna(0).iloc[0]),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        axis=1,
    )
    keep_cols = [
        "case_type",
        "event_id",
        "prefix",
        "source_experiment",
        "default_or_full_label",
        "compared_versions_labels",
        "recommended_priority",
        "as_path_len",
        "run_id",
        "risk_score",
        "certainty_score",
        "conflict_score",
        "collector_count",
        "visibility_count",
        "record_count",
        "top_contributing_factor",
    ]
    keep_cols = [c for c in keep_cols if c in out.columns]
    return out[keep_cols].copy()


def choose_final_tag(cards_df: pd.DataFrame) -> str:
    if cards_df.empty:
        return "case_pool=暂不足以支撑正式E8"
    class_counts = cards_df["case_type"].value_counts().to_dict()
    a_ok = class_counts.get("A_gate_upfloat_block", 0) >= 2
    b_ok = class_counts.get("B_augment_boundary", 0) >= 2
    c_ok = class_counts.get("C_collector_asymmetry", 0) >= 2
    total = len(cards_df)
    if a_ok and b_ok and c_ok and total >= 6:
        return "case_pool=已可进入正式E8"
    if total >= 5:
        return "case_pool=基本可用但需补1轮筛选"
    return "case_pool=暂不足以支撑正式E8"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="E8-A case sampling and unified evidence template generation from existing E6/E7 outputs."
    )
    parser.add_argument("--e6b1-parquet", default=DEFAULT_E6B1_PARQUET)
    parser.add_argument("--e6b2-parquet", default=DEFAULT_E6B2_PARQUET)
    parser.add_argument("--e6b3-parquet", default=DEFAULT_E6B3_PARQUET)
    parser.add_argument("--e7b-samples-csv", default=DEFAULT_E7B_SAMPLES_CSV)
    parser.add_argument("--e7a-settings-csv", default=DEFAULT_E7A_SETTINGS_CSV)
    parser.add_argument("--runs-root", default="data/runs", help="Runs root, used for optional D-pool and C-card enrichment.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--a-limit", type=int, default=3)
    parser.add_argument("--b-limit", type=int, default=3)
    parser.add_argument("--c-limit", type=int, default=3)
    parser.add_argument("--d-limit", type=int, default=3)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    e6b1 = pd.read_parquet(args.e6b1_parquet).copy()
    e6b2 = pd.read_parquet(args.e6b2_parquet).copy()
    e6b3 = pd.read_parquet(args.e6b3_parquet).copy()
    e7b_samples = pd.read_csv(args.e7b_samples_csv).copy()
    e7a_settings = pd.read_csv(args.e7a_settings_csv).copy() if Path(args.e7a_settings_csv).exists() else pd.DataFrame()

    # Ensure numeric/bool fields are typed for sorting and summary.
    for df in (e6b1, e6b2, e6b3):
        for col in ["risk_score", "certainty_score", "conflict_score", "evidence_support_score", "structural_novelty_score"]:
            if col in df.columns:
                df[col] = to_num(df[col])
        if "missing_origin_or_path" in df.columns:
            df["missing_origin_or_path"] = to_bool(df["missing_origin_or_path"])

    a_cases = choose_a_cases(e6b1, limit=args.a_limit)
    b_cases = choose_b_cases(e6b2, limit=args.b_limit)
    c_cases = choose_c_cases(e7b_samples, limit=args.c_limit)

    cards_df, summary_df = build_cards(
        a_cases=a_cases,
        b_cases=b_cases,
        c_cases=c_cases,
        e6b3_map=e6b3,
        e7a_settings=e7a_settings,
        runs_root=Path(args.runs_root),
    )

    # D class is optional backup pool, non-blocking.
    base_run_id = str(e6b3["run_id"].iloc[0]) if "run_id" in e6b3.columns and len(e6b3) else ""
    d_pool_df = build_d_pool(run_id=base_run_id, runs_root=Path(args.runs_root), limit=args.d_limit) if base_run_id else pd.DataFrame()

    # Persist outputs.
    cards_df.to_csv(output_dir / "e8a_case_cards_minimal.csv", index=False, encoding="utf-8-sig")
    summary_df.to_csv(output_dir / "e8a_case_candidates_abc.csv", index=False, encoding="utf-8-sig")
    if d_pool_df.empty:
        pd.DataFrame(
            [{"note": "No eligible D-class stealth backup found under current low-visibility + strong-structural criteria."}]
        ).to_csv(output_dir / "e8a_case_candidates_d_stealth.csv", index=False, encoding="utf-8-sig")
    else:
        d_pool_df.to_csv(output_dir / "e8a_case_candidates_d_stealth.csv", index=False, encoding="utf-8-sig")

    template_md = build_template_markdown()
    (output_dir / "e8a_case_template.md").write_text(template_md, encoding="utf-8")

    class_counts = cards_df["case_type"].value_counts().to_dict() if not cards_df.empty else {}
    final_tag = choose_final_tag(cards_df)
    summary = {
        "output_dir": str(output_dir.resolve()),
        "inputs": {
            "e6b1_parquet": str(Path(args.e6b1_parquet).resolve()),
            "e6b2_parquet": str(Path(args.e6b2_parquet).resolve()),
            "e6b3_parquet": str(Path(args.e6b3_parquet).resolve()),
            "e7b_samples_csv": str(Path(args.e7b_samples_csv).resolve()),
            "e7a_settings_csv": str(Path(args.e7a_settings_csv).resolve()) if Path(args.e7a_settings_csv).exists() else "",
            "runs_root": str(Path(args.runs_root).resolve()),
        },
        "candidate_counts": {
            "A_gate_upfloat_block": int(class_counts.get("A_gate_upfloat_block", 0)),
            "B_augment_boundary": int(class_counts.get("B_augment_boundary", 0)),
            "C_collector_asymmetry": int(class_counts.get("C_collector_asymmetry", 0)),
            "ABC_total": int(len(cards_df)),
            "D_stealth_backup": int(len(d_pool_df)) if not d_pool_df.empty else 0,
        },
        "collector_identity": {
            "full_collectors": "route-views.sg,rrc00",
            "single_collectors": ["route-views.sg_only", "rrc00_only"],
        },
        "final_tag": final_tag,
    }
    (output_dir / "e8a_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"A_selected={int(class_counts.get('A_gate_upfloat_block', 0))}")
    print(f"B_selected={int(class_counts.get('B_augment_boundary', 0))}")
    print(f"C_selected={int(class_counts.get('C_collector_asymmetry', 0))}")
    print(f"ABC_total={int(len(cards_df))}")
    print(f"D_backup={int(len(d_pool_df)) if not d_pool_df.empty else 0}")
    print(f"final_tag={final_tag}")


if __name__ == "__main__":
    main()
