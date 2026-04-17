import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd


CAIDA_REL_DEFAULT = "/mainrepo/data/caida/as-relationships/serial-2/20170701.as-rel2.txt"
KNOWN_EVENT_MANIFEST_DEFAULT = "data/known_events/known_event_candidates_v02.json"


EVENT_CANDIDATES = [
    {
        "event_name": "Rostelecom AS12389 suspicious-origin burst",
        "slug": "rostelecom_20170426",
        "approximate_time_window": "2017-04-26 22:36-22:43 UTC",
        "collect_from": "2017-04-26 22:34:00",
        "minutes": 12,
        "target_prefixes": ["203.112.90.0/24"],
        "known_origin_or_attack_as": "malicious_origin=AS12389 (example victim aggregate: AS9221 /23)",
        "known_malicious_origin_asn": 12389,
        "known_attacker_asns": [12389],
        "public_source_hint": "BGPmon 'Curious Case of AS12389' (2017-04-27), with prefix example 203.112.90.0/24 and event window.",
        "source_reference": "https://www2.bgpmon.net/bgpstream-and-the-curious-case-of-as12389/",
        "selected_for_test": True,
        "selection_reason": "2017 event, minute-level window, explicit prefix/ASN anchor, low incremental collection cost.",
        "fit_reason": "Tests forged-origin/suspicious-origin handling and layer split under short burst conditions.",
    },
    {
        "event_name": "Google-Verizon route leak (Japan impact)",
        "slug": "google_verizon_20170825",
        "approximate_time_window": "2017-08-25 03:22-03:33 UTC",
        "collect_from": "2017-08-25 03:20:00",
        "minutes": 15,
        "target_prefixes": ["114.154.133.0/24"],
        "known_origin_or_attack_as": "example affected prefix tied to AS4713; leak path propagated via AS15169 and AS701",
        "known_malicious_origin_asn": None,
        "known_attacker_asns": [15169, 701],
        "public_source_hint": "BGPmon 2017-08-26 analysis with example 114.154.133.0/24; leak interval 03:22-03:33 UTC.",
        "source_reference": "https://www.bgpmon.net/bgp-leak-causing-internet-outages-in-japan-and-beyond/",
        "selected_for_test": True,
        "selection_reason": "2017 event with explicit time/prefix and direct fit to partial-observability + route-leak stress test.",
        "fit_reason": "Validates whether system gives explainable response to known route-leak style anomalies.",
    },
    {
        "event_name": "Amazon Route53 / MyEtherWallet hijack",
        "slug": "route53_mew_20180424",
        "approximate_time_window": "2018-04-24 11:05-12:55 UTC",
        "collect_from": "2018-04-24 11:03:00",
        "minutes": 15,
        "target_prefixes": ["205.251.192.0/24", "205.251.194.0/24", "205.251.196.0/24", "205.251.198.0/24"],
        "known_origin_or_attack_as": "malicious_origin=AS10297 against Amazon Route53 space (legit AS16509 aggregate)",
        "known_malicious_origin_asn": 10297,
        "known_attacker_asns": [10297],
        "public_source_hint": "Internet Society MANRS post with malicious /24 set and 11:05 UTC onset details.",
        "source_reference": "https://www.internetsociety.org/blog/2018/04/amazons-route-53-bgp-hijack/",
        "selected_for_test": True,
        "selection_reason": "Strong public anchor (time + malicious origins + prefixes); 2018 but still low-cost short-window replay.",
        "fit_reason": "Classic forged-origin style hijack with strong external anchor for capability backstop.",
    },
    {
        "event_name": "MainOne / China Telecom Google route leak",
        "slug": "mainone_20181112",
        "approximate_time_window": "2018-11-12 around 21:00-22:30 UTC",
        "collect_from": "2018-11-12 21:00:00",
        "minutes": 15,
        "target_prefixes": ["8.8.8.0/24"],
        "known_origin_or_attack_as": "reported leak chain includes AS37282 and AS4134",
        "known_malicious_origin_asn": None,
        "known_attacker_asns": [37282, 4134],
        "public_source_hint": "Cyberstability Nov-2018 roundup citing public analyses of MainOne/China Telecom reroute; used only as backup candidate.",
        "source_reference": "https://cyberstability.org/news/cyberstability-update-november-2018.html",
        "selected_for_test": False,
        "selection_reason": "Held as backup: public awareness high but prefix-level reproducibility under current minimal-cost setup is weaker.",
        "fit_reason": "Useful reference event, but lower reproducibility confidence than selected set under strict low-cost constraints.",
    },
]


def load_event_candidates(manifest_path: str | None = None) -> list[dict[str, Any]]:
    if not manifest_path:
        return list(EVENT_CANDIDATES)

    path = Path(manifest_path)
    if not path.exists():
        raise SystemExit(f"known-event manifest not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        events = payload.get("events", [])
    elif isinstance(payload, list):
        events = payload
    else:
        raise SystemExit(f"invalid manifest format: {path}")

    if not isinstance(events, list) or not events:
        raise SystemExit(f"manifest contains no events: {path}")

    return [dict(x) for x in events]


def select_event_candidates(
    events: list[dict[str, Any]],
    *,
    selected_only: bool = False,
    inventory_stage: str = "",
    event_slugs: str = "",
) -> list[dict[str, Any]]:
    out = list(events)

    if selected_only:
        out = [e for e in out if e.get("selected_for_test", False)]

    stage = str(inventory_stage or "").strip()
    if stage:
        out = [e for e in out if str(e.get("inventory_stage", "")).strip() == stage]

    slug_text = str(event_slugs or "").strip()
    if slug_text:
        slug_set = {x.strip() for x in slug_text.split(",") if x.strip()}
        out = [e for e in out if str(e.get("slug", "")).strip() in slug_set]

    return out


FINAL_LABEL_ORDER = {
    "high_priority_alert": 0,
    "needs_review": 1,
    "low_priority_or_background": 2,
}


def to_bool(v: Any) -> bool:
    text = str(v).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def run_cmd(cmd: list[str], workdir: Path) -> None:
    print("[CMD]", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(workdir))
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def parse_as_path(path_val: Any) -> set[int]:
    text = str(path_val or "").strip()
    if not text:
        return set()
    out = set()
    for token in text.split(" "):
        token = token.strip()
        if token.isdigit():
            out.add(int(token))
    return out


def normalize_label(v: str) -> str:
    if v == "high_priority_alert":
        return "high"
    if v == "needs_review":
        return "needs"
    if v == "low_priority_or_background":
        return "low"
    return v


def run_pipeline_for_event(
    *,
    event: dict[str, Any],
    workdir: Path,
    runs_root: Path,
    collectors: str,
    max_rows: int,
    caida_rel: str,
    force: bool,
    run_id_prefix: str = "e8c",
    marker_dir_name: str = "markers_e8c",
) -> str:
    run_id = f"{run_id_prefix}_{event['slug']}"
    run_dir = runs_root / run_id
    final_path = run_dir / "final" / "final_alerts.parquet"
    if final_path.exists() and not force:
        print(f"[SKIP] reuse existing run: {run_id}")
        return run_id

    run_dir.mkdir(parents=True, exist_ok=True)
    marker_dir = workdir / "data" / marker_dir_name
    marker_dir.mkdir(parents=True, exist_ok=True)

    run_cmd(
        [
            sys.executable,
            "scripts/run.py",
            "--from",
            event["collect_from"],
            "--minutes",
            str(event["minutes"]),
            "--chunk-minutes",
            "5",
            "--collectors",
            collectors,
            "--record-type",
            "updates",
            "--format",
            "parquet",
            "--max-rows",
            str(max_rows),
            "--run-id",
            run_id,
            "--marker-dir",
            str(marker_dir),
            "--caida-rel",
            caida_rel,
        ],
        workdir=workdir,
    )

    events_path = run_dir / "events" / "event_units.parquet"
    baseline_dir = run_dir / "baseline"
    candidates_dir = run_dir / "candidates"
    scores_dir = run_dir / "scores"
    gating_dir = run_dir / "gating"
    aug_dir = run_dir / "augmentation"
    final_dir = run_dir / "final"

    run_cmd(
        [
            sys.executable,
            "scripts/build_event_units.py",
            "--run-id",
            run_id,
            "--input",
            str(run_dir),
            "--output",
            str(events_path),
            "--window-sec",
            "300",
            "--prefer-rel",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/build_historical_baseline.py",
            "--run-id",
            run_id,
            "--input",
            str(events_path),
            "--output-dir",
            str(baseline_dir),
            "--min-events",
            "1",
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/build_weak_candidates.py",
            "--run-id",
            run_id,
            "--events",
            str(events_path),
            "--baseline-prefix",
            str(baseline_dir / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(baseline_dir / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(baseline_dir / "baseline_path.parquet"),
            "--output-dir",
            str(candidates_dir),
            "--min-weak-rules",
            "2",
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/score_weak_candidates.py",
            "--run-id",
            run_id,
            "--candidates",
            str(candidates_dir / "candidate_events.parquet"),
            "--baseline-prefix",
            str(baseline_dir / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(baseline_dir / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(baseline_dir / "baseline_path.parquet"),
            "--output-dir",
            str(scores_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/gate_scored_candidates.py",
            "--run-id",
            run_id,
            "--scores",
            str(scores_dir / "scored_candidates.parquet"),
            "--output-dir",
            str(gating_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/augment_uncertain_candidates.py",
            "--run-id",
            run_id,
            "--gating",
            str(gating_dir / "gated_candidates.parquet"),
            "--events",
            str(events_path),
            "--baseline-prefix",
            str(baseline_dir / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(baseline_dir / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(baseline_dir / "baseline_path.parquet"),
            "--output-dir",
            str(aug_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/build_final_alerts.py",
            "--run-id",
            run_id,
            "--gating",
            str(gating_dir / "gated_candidates.parquet"),
            "--augmentation",
            str(aug_dir / "augmented_candidates.parquet"),
            "--scores",
            str(scores_dir / "scored_candidates.parquet"),
            "--output-dir",
            str(final_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    return run_id


def check_match(
    *,
    known_origin_asn: Any,
    known_attacker_asns: list[int],
    origin_as: Any,
    as_path_clean: Any,
) -> tuple[str, str]:
    origin_num = pd.to_numeric(pd.Series([origin_as]), errors="coerce").iloc[0]
    path_asns = parse_as_path(as_path_clean)

    if known_origin_asn is None:
        origin_match = "unknown"
    elif pd.isna(origin_num):
        origin_match = "unknown"
    else:
        origin_match = "yes" if int(origin_num) == int(known_origin_asn) else "no"

    if not known_attacker_asns:
        attacker_match = "unknown"
    else:
        attacker_set = set(int(x) for x in known_attacker_asns)
        hit = False
        if not pd.isna(origin_num) and int(origin_num) in attacker_set:
            hit = True
        if attacker_set & path_asns:
            hit = True
        attacker_match = "yes" if hit else "no"
    return origin_match, attacker_match


def evaluate_event_result(event: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    target_prefixes = set(event["target_prefixes"])
    events_path = run_dir / "events" / "event_units.parquet"
    candidates_path = run_dir / "candidates" / "candidate_events.parquet"
    final_path = run_dir / "final" / "final_alerts.parquet"

    events_df = pd.read_parquet(events_path) if events_path.exists() else pd.DataFrame()
    cand_df = pd.read_parquet(candidates_path) if candidates_path.exists() else pd.DataFrame()
    final_df = pd.read_parquet(final_path) if final_path.exists() else pd.DataFrame()

    event_rows = events_df[events_df.get("prefix", "").astype(str).isin(target_prefixes)].copy() if not events_df.empty else pd.DataFrame()
    final_rows = final_df[final_df.get("prefix", "").astype(str).isin(target_prefixes)].copy() if not final_df.empty else pd.DataFrame()

    if not final_rows.empty:
        final_rows["label_rank"] = final_rows["final_alert_label"].map(FINAL_LABEL_ORDER).fillna(9)
        final_rows["risk_num"] = pd.to_numeric(final_rows.get("risk_score", 0.0), errors="coerce").fillna(0.0)
        best = final_rows.sort_values(["label_rank", "risk_num"], ascending=[True, False]).iloc[0]

        origin_match, attacker_match = check_match(
            known_origin_asn=event.get("known_malicious_origin_asn", None),
            known_attacker_asns=event.get("known_attacker_asns", []),
            origin_as=best.get("origin_as", None),
            as_path_clean=best.get("as_path_clean", ""),
        )

        if (origin_match == "yes") and (attacker_match in {"yes", "unknown"}):
            strength = "strong"
        elif attacker_match == "yes" or origin_match == "yes":
            strength = "partial"
        else:
            strength = "weak"

        return {
            "event_name": event["event_name"],
            "tested_time_window": f"{event['collect_from']} +{event['minutes']}m",
            "target_prefix": "|".join(event["target_prefixes"]),
            "system_hit": "yes",
            "matched_event_id": str(best.get("event_id", "")),
            "final_label": normalize_label(str(best.get("final_alert_label", ""))),
            "risk": float(pd.to_numeric(pd.Series([best.get("risk_score", 0.0)]), errors="coerce").fillna(0.0).iloc[0]),
            "certainty": float(pd.to_numeric(pd.Series([best.get("certainty_score", 0.0)]), errors="coerce").fillna(0.0).iloc[0]),
            "origin_match": origin_match,
            "attacker_as_match": attacker_match,
            "match_strength": strength,
            "no_hit_reason": "",
            "short_interpretation": (
                f"Hit target prefix in `{normalize_label(str(best.get('final_alert_label', '')))}` with "
                f"risk={float(pd.to_numeric(pd.Series([best.get('risk_score', 0.0)]), errors='coerce').fillna(0.0).iloc[0]):.2f}."
            ),
        }

    # No final hit: classify reason conservatively.
    if event_rows.empty:
        reason = "no_visibility"
    else:
        if not cand_df.empty:
            cand_rows = cand_df[cand_df.get("prefix", "").astype(str).isin(target_prefixes)].copy()
            if cand_rows.empty:
                reason = "no_event_constructed"
            else:
                promoted = cand_rows["candidate_flag"].fillna(False).astype(bool).any() if "candidate_flag" in cand_rows.columns else False
                reason = "weak_signal_not_enough" if not promoted else "unknown_needs_manual_check"
        else:
            reason = "unknown_needs_manual_check"

    return {
        "event_name": event["event_name"],
        "tested_time_window": f"{event['collect_from']} +{event['minutes']}m",
        "target_prefix": "|".join(event["target_prefixes"]),
        "system_hit": "no",
        "matched_event_id": "",
        "final_label": "",
        "risk": 0.0,
        "certainty": 0.0,
        "origin_match": "unknown",
        "attacker_as_match": "unknown",
        "match_strength": "weak",
        "no_hit_reason": reason,
        "short_interpretation": f"No final label hit under current collector visibility; classified as `{reason}`.",
    }


def build_known_event_test_markdown(
    *,
    candidates_df: pd.DataFrame,
    results_df: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# E8-C Known Public Event Test")
    lines.append("")
    lines.append(f"- candidate_events: {int(summary['candidate_events'])}")
    lines.append(f"- selected_for_test: {int(summary['selected_for_test'])}")
    lines.append(f"- tested_events: {int(summary['tested_events'])}")
    lines.append(f"- hit_events: {int(summary['hit_events'])}")
    lines.append("")
    lines.append("## Candidate List")
    lines.append("")
    lines.append("| event_name | time_window | target_prefixes | known_origin_or_attack_as | selected_for_test | selection_reason | source_reference |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in candidates_df.iterrows():
        lines.append(
            f"| {r['event_name']} | {r['time_window']} | {r['prefix']} | {r['origin_as_or_suspected_as']} | "
            f"{r['selected_for_test']} | {r['selection_reason']} | {r['source_reference']} |"
        )
    lines.append("")
    lines.append("## Detection Results (Selected Set)")
    lines.append("")
    lines.append("| event_name | system_hit | matched_event_id | final_label | risk | certainty | origin_match | attacker_as_match | match_strength | no_hit_reason |")
    lines.append("|---|---|---|---|---:|---:|---|---|---|---|")
    for _, r in results_df.iterrows():
        lines.append(
            f"| {r['event_name']} | {r['system_hit']} | {r['matched_event_id']} | {r['final_label']} | "
            f"{float(r['risk']):.2f} | {float(r['certainty']):.2f} | {r['origin_match']} | {r['attacker_as_match']} | "
            f"{r['match_strength']} | {r['no_hit_reason']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="E8-C: small-scale known public BGP event test with minimal incremental data cost.")
    parser.add_argument("--output-dir", default="outputs/e8c_known_events_test_v01")
    parser.add_argument("--runs-root", default="data/runs")
    parser.add_argument("--manifest", default=KNOWN_EVENT_MANIFEST_DEFAULT, help="JSON manifest for known-event candidates.")
    parser.add_argument("--selected-only", default="true", help="When true, only run events with selected_for_test=true.")
    parser.add_argument("--inventory-stage", default="", help="Optional inventory_stage filter such as core_tested or next_batch.")
    parser.add_argument("--event-slugs", default="", help="Optional comma-separated slug filter.")
    parser.add_argument("--collectors", default="route-views.sg,rrc00")
    parser.add_argument("--max-rows", type=int, default=50000)
    parser.add_argument("--caida-rel", default=CAIDA_REL_DEFAULT)
    parser.add_argument("--execute", default="true", help="Run collection+pipeline for selected events.")
    parser.add_argument("--force", default="false", help="Force rerun even if final artifacts already exist.")
    parser.add_argument("--run-id-prefix", default="e8c", help="Prefix used for generated run_id values.")
    args = parser.parse_args()

    workdir = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_root = Path(args.runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    do_execute = to_bool(args.execute)
    force = to_bool(args.force)
    event_candidates = load_event_candidates(args.manifest)
    selected_events = select_event_candidates(
        event_candidates,
        selected_only=to_bool(args.selected_only),
        inventory_stage=args.inventory_stage,
        event_slugs=args.event_slugs,
    )

    candidate_rows = []
    for e in selected_events if to_bool(args.selected_only) or args.inventory_stage or args.event_slugs else event_candidates:
        candidate_rows.append(
            {
                "event_name": e["event_name"],
                "inventory_stage": e.get("inventory_stage", ""),
                "selection_priority": e.get("selection_priority", ""),
                "reproducibility_confidence": e.get("reproducibility_confidence", ""),
                "public_source_hint": e["public_source_hint"],
                "time_window": e["approximate_time_window"],
                "prefix": "|".join(e["target_prefixes"]),
                "origin_as_or_suspected_as": e["known_origin_or_attack_as"],
                "selected_for_test": "yes" if e["selected_for_test"] else "no",
                "selection_reason": e["selection_reason"],
                "source_reference": e["source_reference"],
                "fit_reason": e["fit_reason"],
            }
        )
    candidates_df = pd.DataFrame(candidate_rows)
    candidates_df.to_csv(output_dir / "e8c_known_events_candidates.csv", index=False, encoding="utf-8-sig")

    selected = selected_events
    results = []
    for e in selected:
        run_id = f"e8c_{e['slug']}"
        if do_execute:
            run_id = run_pipeline_for_event(
                event=e,
                workdir=workdir,
                runs_root=runs_root,
                collectors=args.collectors,
                max_rows=args.max_rows,
                caida_rel=args.caida_rel,
                force=force,
                run_id_prefix=args.run_id_prefix,
            )
        run_dir = runs_root / run_id
        result = evaluate_event_result(e, run_dir)
        result["run_id"] = run_id
        results.append(result)

    results_df = pd.DataFrame(results)
    results_df.to_csv(output_dir / "e8c_known_events_test_results.csv", index=False, encoding="utf-8-sig")

    hit_df = results_df[results_df["system_hit"] == "yes"].copy()
    nohit_df = results_df[results_df["system_hit"] != "yes"].copy()
    nohit_df = nohit_df[["event_name", "no_hit_reason", "short_interpretation"]].copy()
    nohit_df.to_csv(output_dir / "e8c_known_events_nohit_reasons.csv", index=False, encoding="utf-8-sig")

    label_counts = (
        hit_df["final_label"].value_counts().to_dict() if not hit_df.empty else {}
    )
    summary = {
        "candidate_events": int(len(candidates_df)),
        "selected_for_test": int(len(selected)),
        "tested_events": int(len(results_df)),
        "hit_events": int((results_df["system_hit"] == "yes").sum()),
        "unhit_events": int((results_df["system_hit"] != "yes").sum()),
        "hit_label_distribution": {str(k): int(v) for k, v in label_counts.items()},
        "match_strength_distribution": {str(k): int(v) for k, v in results_df["match_strength"].value_counts().to_dict().items()},
        "origin_match_distribution": {str(k): int(v) for k, v in results_df["origin_match"].value_counts().to_dict().items()},
        "attacker_as_match_distribution": {str(k): int(v) for k, v in results_df["attacker_as_match"].value_counts().to_dict().items()},
        "selected_run_ids": [f"{args.run_id_prefix}_{e['slug']}" for e in selected],
    }
    (output_dir / "e8c_known_events_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md_text = build_known_event_test_markdown(
        candidates_df=candidates_df,
        results_df=results_df,
        summary=summary,
    )
    (output_dir / "e8c_known_events_test.md").write_text(md_text, encoding="utf-8")

    print(f"candidate_events={summary['candidate_events']}")
    print(f"selected_for_test={summary['selected_for_test']}")
    print(f"tested_events={summary['tested_events']}")
    print(f"hit_events={summary['hit_events']}")
    print(f"hit_label_distribution={summary['hit_label_distribution']}")
    print(f"match_strength_distribution={summary['match_strength_distribution']}")


if __name__ == "__main__":
    main()
