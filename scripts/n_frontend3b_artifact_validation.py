"""Recompute 3B artifact invariants without importing the routing runner."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from n_frontend3b_contract import (
    canonical, digest, file_hash, normalized, read_json, require,
    same_table, table_records, verify_source, verify_variant_frames,
)

FG = "semantic_foreground"
BG = "reversible_background_summary"
GRAY = "gray_contract_anomaly"
KEEP = "protected_semantic_foreground"
DROP = "suppressible_semantic_redundancy"


def cell(value):
    value = normalized(value)
    if isinstance(value, str) and value.startswith(("[", "{")):
        try:
            return normalized(json.loads(value))
        except ValueError:
            pass
    return value


def csv_records(frame, columns=None):
    if columns is not None:
        require(set(columns) <= set(frame), "missing CSV metric columns")
        frame = frame[columns]
    return sorted(({k: cell(v) for k, v in row.items()} for row in frame.to_dict("records")), key=canonical)


def check_csv(expected, path, columns=None):
    actual = pd.read_csv(path, float_precision="round_trip")
    require(csv_records(expected, columns) == csv_records(actual, columns), f"recomputed CSV mismatch:{Path(path).name}")


def exposure(lineage, transitions):
    """Independent tabular strict-prior query using the frozen 2B semantics."""
    index = transitions.set_index("transition_id", drop=False)
    prep = set(lineage.loc[lineage.is_poisoning_preparation_member, "observation_id"].dropna())
    known = set(lineage.observation_id.dropna())
    rows = []
    for attack in lineage[lineage.is_attack_member & lineage.expected_visible].to_dict("records"):
        current = index.loc[attack["transition_id"]]
        ts, signature = float(current.transition_ts), current.new_route_signature
        prior = transitions[(transitions.new_route_signature == signature) & (transitions.transition_ts < ts)]
        prior = prior.sort_values(["transition_ts", "transition_id"])
        times = prior.transition_ts.astype(float).tolist()
        peer_set = sorted(set(prior.peer_address.dropna()))
        collector_set = sorted(set(prior.collector.dropna()))
        ids = {member for members in prior.member_observation_ids for member in members} & known
        withdrawn = transitions[
            (transitions.collector == current.collector) & (transitions.peer_address == current.peer_address)
            & (transitions.prefix == current.prefix) & (transitions.transition_ts < ts)
            & transitions.transition_family.isin(["bootstrap_withdrawal", "withdrawal", "repeated_withdrawal", "state_recovery_withdraw"])
        ]
        rows.append({
            **{k: attack[k] for k in ("pair_id", "variant_role", "collector", "peer_address")},
            "attack_observation_id": attack["observation_id"], "attack_ts": ts, "route_signature": signature,
            "previously_exposed": bool(times), "prior_exposure_count": len(prior),
            "first_seen_ts": times[0] if times else None, "first_seen_age_sec": ts-times[0] if times else None,
            "last_seen_ts": times[-1] if times else None, "last_seen_gap_sec": ts-times[-1] if times else None,
            "ordered_prior_transition_ids": list(prior.transition_id), "ordered_prior_transition_ts": times,
            "ordered_inter_arrival_gaps_sec": [b-a for a, b in zip(times, times[1:])],
            "distinct_prior_300s_bucket_count": len({math.floor(t/300) for t in times}),
            "distinct_prior_utc_day_count": len({pd.Timestamp(t, unit="s", tz="UTC").date() for t in times}),
            "distinct_prior_peer_count": len(peer_set), "distinct_prior_peer_set": peer_set,
            "distinct_prior_collector_count": len(collector_set), "distinct_prior_collector_set": collector_set,
            "prior_withdrawal_count": len(withdrawn),
            "exposure_only_in_poisoning_preparation": bool(times) and bool(ids) and ids <= prep,
            "maximum_contributing_transition_ts": times[-1] if times else None,
            "causality_valid": all(t < ts for t in times), "bounded_proxy": True,
        })
    return pd.DataFrame(rows)


def verify_artifacts(output, config, independent_assignment, allow_self_test=False):
    output = Path(output)
    manifest = read_json(output / "n_frontend3b_frozen_input_manifest.json")
    self_test = manifest.get("self_test") is True
    require(not self_test or allow_self_test, "self-test artifacts are not formal evidence")
    context = verify_source(Path(manifest["source_2b_root"]), config, self_test)
    require(manifest.get("input_sha256") == context["input_sha256"], "source changed since routing")
    source_root = Path(context["source_2b_root"])
    truth = context["truth"]
    denominators, transition_loads, micro_loads, safety = [], [], [], []
    semantic_assignments, semantic_micro = [], []
    restoration_rows, causal_rows, equality_rows, distributions = [], [], [], []
    non_route_rows = []
    total_gray = 0
    variants = sorted((output / "evaluation_only").glob("*/*"))
    require({(v.parent.name, v.name) for v in variants} ==
            {(v.parent.name, v.name) for v in (source_root / "evaluation_only").glob("*/*")}, "output variant set mismatch")
    for variant in variants:
        pair, role = variant.parent.name, variant.name
        source_dir = source_root / "evaluation_only" / pair / role
        m = read_json(variant / "n_frontend3b_variant_manifest.json")
        for label, name in (("transition", "frontend/n_frontend1_transitions.parquet"),
                            ("micro_event", "frontend/n_frontend1_micro_events.parquet"),
                            ("lineage", "phase_survival_lineage.csv"), ("exposure", "past_only_route_exposure.csv")):
            require(Path(m[f"source_{label}_path"]).resolve() == (source_dir / name).resolve(), "variant source path mismatch")
            require(m[f"source_{label}_sha256"] == file_hash(source_dir / name), "variant source hash mismatch")
        source = pd.read_parquet(source_dir / "frontend/n_frontend1_transitions.parquet")
        events = pd.read_parquet(source_dir / "frontend/n_frontend1_micro_events.parquet")
        lineage = pd.read_csv(source_dir / "phase_survival_lineage.csv")
        local_truth = truth[(truth.pair_id == pair) & (truth.variant_role == role)]
        verify_variant_frames(source, events, lineage, local_truth, context["episode_start_ts"], context["episode_end_ts"])
        assignments = pd.read_parquet(variant / "n_frontend3b_transition_assignments.parquet")
        routed = pd.read_parquet(variant / "n_frontend3b_micro_event_routing.parquet")
        require(not assignments.transition_id.duplicated().any() and set(assignments.transition_id) == set(source.transition_id), "assignment IDs mismatch")
        require(not routed.micro_event_id.duplicated().any() and set(routed.micro_event_id) == set(events.micro_event_id), "routing IDs mismatch")
        expected = {r["transition_id"]: independent_assignment(r, config) for r in source.to_dict("records")}
        expected_event, membership = {}, {}
        for event in events.to_dict("records"):
            choices = [expected[t] for t in event["member_transition_ids"]]
            route = FG if KEEP in choices else GRAY if GRAY in choices else BG
            expected_event[event["micro_event_id"]] = route
            membership.update({t: event["micro_event_id"] for t in event["member_transition_ids"]})
        source_event_members = dict(zip(events.micro_event_id, events.member_transition_ids))
        require(all(row.final_route == expected_event[row.micro_event_id] and
                    list(row.member_transition_ids) == list(source_event_members[row.micro_event_id])
                    for row in routed.itertuples()), "source micro-event routing mismatch")
        expected_routes = {t: expected_event[e] for t, e in membership.items()}
        require(all(r.eligibility_assignment == expected[r.transition_id] and r.final_route == expected_routes[r.transition_id]
                    and r.micro_event_id == membership[r.transition_id] for r in assignments.itertuples()), "independent routing mismatch")
        total_gray += sum(value == GRAY for value in expected.values())
        shared = [c for c in assignments if c in source]
        require(same_table(assignments[shared], source[shared]), "assignment source fields changed")
        # The learning files themselves must contain exactly the source events
        # selected by precedence, not just agree with a separate routing table.
        restored_parts = []
        for route, filename in ((FG, "semantic_foreground_transitions.parquet"),
                                (BG, "immutable_background_transitions.parquet"), (GRAY, "gray_contract_anomaly_transitions.parquet")):
            actual = pd.read_parquet(variant / filename)
            selected = source[source.transition_id.map(expected_routes) == route]
            require(same_table(selected, actual), f"persisted transition content mismatch:{filename}")
            restored_parts.append(actual)
        for route, filename in ((FG, "semantic_foreground_micro_events.parquet"), (BG, "reversible_background_micro_events.parquet")):
            require(same_table(events[events.micro_event_id.map(expected_event) == route], pd.read_parquet(variant / filename)), f"learning micro-event content mismatch:{filename}")
        restored = pd.concat(restored_parts, ignore_index=True)
        require(same_table(source, restored), "full restoration mismatch")
        background = restored_parts[1]
        index = pd.read_parquet(variant / "n_frontend3b_reversible_background_index.parquet")
        expected_index = []
        for key, group in background.groupby(["collector", "peer_address", "prefix", "new_route_signature"], dropna=False):
            group = group.sort_values(["transition_ts", "transition_id"])
            times = group.transition_ts.astype(float).tolist()
            expected_index.append({"collector": key[0], "peer_address": key[1], "prefix": key[2], "route_signature": key[3],
                "first_ts": times[0], "last_ts": times[-1], "member_count": len(group),
                "ordered_transition_ids": list(group.transition_id), "ordered_transition_ts": times,
                "ordered_inter_arrival_gaps_sec": [b-a for a,b in zip(times,times[1:])],
                "member_observation_ids": sorted({i for ids in group.member_observation_ids for i in ids}),
                "source_files": sorted({p for paths in group.source_files for p in paths}),
                "immutable_member_store": str(variant / "immutable_background_transitions.parquet")})
        require(table_records(pd.DataFrame(expected_index)) == table_records(index), "background index content mismatch")
        members = pd.read_parquet(variant / "n_frontend3b_background_member_manifest.parquet")
        member_columns = ["transition_id", "transition_ts", "collector", "peer_address", "prefix", "new_route_signature", "member_observation_ids", "source_files", "micro_event_id", "final_route"]
        expected_members = assignments[assignments.final_route == BG][member_columns].copy()
        expected_members["immutable_member_store"] = str(variant / "immutable_background_transitions.parquet")
        require(same_table(expected_members, members), "background member manifest mismatch")
        before, after = exposure(lineage, source), exposure(lineage, restored)
        require(same_table(before, after), "joint history changed")
        check_csv(before, variant / "n_frontend3b_past_only_exposure_pre.csv")
        check_csv(after, variant / "n_frontend3b_past_only_exposure_post.csv")
        baseline = pd.read_csv(source_dir / "past_only_route_exposure.csv")
        check_csv(before, source_dir / "past_only_route_exposure.csv", list(baseline.columns))
        eq = []
        for row in before.to_dict("records"):
            keys = ["pair_id", "variant_role", "collector", "peer_address", "attack_observation_id"]
            eq.append({**{k: str(row[k]) for k in keys}, "pre_row_sha256": digest(row), "post_row_sha256": digest(row), "mismatch_columns": [], "exact_equal": True})
        check_csv(pd.DataFrame(eq), variant / "n_frontend3b_past_only_exposure_equality.csv")
        equality_rows.extend({"source_pair_id": pair, "source_variant_role": role, **row} for row in eq)
        # Rebuild the ordered ledger instead of checking only sibling equality.
        ledger = digest({"ledger": "n_frontend3b_empty_v1"})
        assignment_index = assignments.set_index("transition_id")
        for ts, batch in source.sort_values(["transition_ts", "transition_id"]).groupby("transition_ts", sort=False):
            require(all(assignment_index.loc[t, "decision_prior_ledger_fingerprint"] == ledger for t in batch.transition_id), "prior ledger fingerprint mismatch")
            updates = [{"transition_id": r.transition_id, "transition_ts": float(ts),
                        "state_key": [r.collector, r.peer_address, r.prefix, normalized(r.path_id) or ""],
                        "new_route_signature": normalized(r.new_route_signature), "transition_family": r.transition_family,
                        "eligibility_assignment": expected[r.transition_id]} for r in batch.itertuples()]
            ledger = digest({"prior": ledger, "batch": sorted(updates, key=lambda r:r["transition_id"])})
        require(ledger == m["final_ledger_fingerprint"], "final ledger fingerprint mismatch")
        causal_rows.append({"pair_id": pair, "variant_role": role, "transition_count":len(source),
                            "assignment_table_equal":True,"primary_ledger_fingerprint":ledger,
                            "replay_ledger_fingerprint":ledger,"ledger_fingerprint_equal":True,"passed":True})
        ids = sorted(source.transition_id.astype(str))
        restoration_rows.append({"pair_id":pair,"variant_role":role,"input_transition_count":len(source),
            "restored_transition_count":len(source),"unique_input_transition_count":len(set(ids)),
            "unique_restored_transition_count":len(set(ids)),"id_multiset_equal":True,
            "input_transition_id_sha256":digest(ids),"restored_transition_id_sha256":digest(ids),
            "full_member_content_equal":True,"passed":True})
        injected = set(local_truth.observation_id.dropna())
        excluded = {r.transition_id for r in source.itertuples() if set(r.member_observation_ids) & injected}
        excluded_events = {membership[t] for t in excluded}
        eligible_t = set(source.transition_id) - excluded
        eligible_m = set(events.micro_event_id) - excluded_events
        selected_events = events[events.micro_event_id.isin(eligible_m)].copy()
        selected_events["final_route"] = selected_events.micro_event_id.map(expected_event)
        for (count, route), size in selected_events.groupby(["member_transition_count", "final_route"]).size().items():
            distributions.append({"pair_id":pair,"variant_role":role,"population":"unlabeled_operational_background",
                                  "member_transition_count":int(count),"final_route":route,"micro_event_count":int(size)})
        non_route_path = source_dir / "frontend/n_frontend1_non_route_observations.parquet"
        controls = pd.read_parquet(non_route_path)
        control_ids = set(controls.get("observation_id", pd.Series(dtype=object)).dropna())
        routed_ids = {member for members in source.member_observation_ids for member in members}
        consumed = len(control_ids & routed_ids)
        require(consumed == 0, "non-route record entered suppression")
        non_route_rows.append({"pair_id":pair,"variant_role":role,"non_route_source_path":str(non_route_path),
                              "non_route_record_count":len(controls),"non_route_records_consumed_by_suppression":consumed,
                              "bypass_contract":"N-FRONTEND-1 dedicated audit","passed":True})
        denominators.append({"pair_id":pair,"variant_role":role,"transition_total_count":len(source),
            "transition_injected_exclusion_count":len(excluded),"transition_operational_background_count":len(eligible_t),
            "micro_event_total_count":len(events),"micro_event_injected_exclusion_count":len(excluded_events),
            "micro_event_operational_background_count":len(eligible_m),"truth_used_only_after_routing":True})
        for eligible, routes, rows in ((eligible_t,expected_routes,transition_loads),(eligible_m,expected_event,micro_loads)):
            suppressed = sum(routes[t] == BG for t in eligible)
            kept = sum(routes[t] == FG for t in eligible)
            item = {"pair_id":pair,"variant_role":role,"population":"unlabeled_operational_background",
                "background_input_count":len(eligible),"background_routed_count":suppressed,"learning_input_count":kept,
                "gray_count":sum(routes[t] == GRAY for t in eligible),
                "learning_input_reduction_rate":suppressed/len(eligible) if eligible else 0.0,
                "learning_input_compression_ratio":len(eligible)/kept if kept else None}
            if rows is transition_loads:
                item["suppressible_eligibility_count"] = sum(expected[t] == DROP for t in eligible)
            rows.append(item)
        for row in lineage.to_dict("records"):
            tid = normalized(row["transition_id"])
            route = expected_routes.get(tid)
            safety.append({**{k:row[k] for k in ("pair_id","variant_role","phase_id","observation_id","collector","peer_address","transition_id","transition_family","is_attack_member","is_poisoning_preparation_member","expected_visible","observability_boundary")},
                "final_route":route,"traceable_after_routing":bool(tid and route),
                "attack_suppressed":bool(row["is_attack_member"] and row["expected_visible"] and route==BG)})
        semantic_assignments.extend({"pair_id":pair,"variant_role":role,**{k:r[k] for k in ("transition_id","eligibility_assignment","eligibility_reason","micro_event_id","final_route")}} for r in assignments.to_dict("records"))
        semantic_micro.extend({"pair_id":pair,"variant_role":role,**{k:r[k] for k in ("micro_event_id","eligibility_assignment","final_route","routing_reason")}} for r in routed.to_dict("records"))
    for rows, filename in ((denominators,"denominator_audit"),(transition_loads,"transition_learning_load"),
                           (micro_loads,"micro_event_learning_load"),(safety,"phase_survival_regression"),
                           (restoration_rows,"restoration_audit"),(causal_rows,"causal_strict_replay_audit"),
                           (equality_rows,"past_only_exposure_equality"),(distributions,"micro_event_member_distribution"),
                           (non_route_rows,"non_route_bypass_audit")):
        check_csv(pd.DataFrame(rows), output / f"n_frontend3b_{filename}.csv")
    stage_rows = [{"pair_id":r["pair_id"],"variant_role":r["variant_role"],
                   "stage_input_count":r["input_transition_count"],"stage_output_count":r["restored_transition_count"],
                   "passed":True,"stage":"transition_routing_and_restoration","unexplained_loss_count":0}
                  for r in restoration_rows]
    check_csv(pd.DataFrame(stage_rows), output / "n_frontend3b_stage_accounting_audit.csv")
    check_csv(pd.read_csv(source_root / "n_frontend2b_attack_transition_semantic_delta.csv"),
              output / "n_frontend3b_semantic_delta_regression.csv")
    summary = read_json(output / "n_frontend3b_summary.json")
    for rows, prefix in ((transition_loads,"transition"),(micro_loads,"micro_event")):
        n = sum(r["background_input_count"] for r in rows)
        suppressed = sum(r["background_routed_count"] for r in rows)
        require(summary[f"{prefix}_operational_background_input_count"] == n, "summary denominator mismatch")
        require(summary[f"{prefix}_operational_background_suppressed_count"] == suppressed, "summary numerator mismatch")
        require(math.isclose(summary[f"{prefix}_learning_input_reduction_rate"],suppressed/n if n else 0.0,rel_tol=1e-14), "summary rate mismatch")
    require(summary["expected_visible_member_count"] == int(truth.expected_visible.sum()), "summary visible-member mismatch")
    require(summary["observability_boundary_member_count"] == int((~truth.expected_visible).sum()), "summary boundary-member mismatch")
    require(summary["suppressed_attack_count"] == sum(r["attack_suppressed"] for r in safety) == 0, "summary attack count mismatch")
    require(summary["source_2b_registry_fingerprint"] == context["registry_fingerprint"], "summary registry mismatch")
    require(summary["variant_count"] == len(variants) and summary["pair_count"] == len({v.parent.name for v in variants}), "summary variant count mismatch")
    require(total_gray == summary["gray_count"] == 0, "gray contract anomaly")
    sem = {"assignment_count":len(semantic_assignments),"micro_event_count":len(semantic_micro),
        "assignment_fingerprint":digest(sorted(semantic_assignments,key=lambda r:(r["pair_id"],r["variant_role"],r["transition_id"]))),
        "micro_event_fingerprint":digest(sorted(semantic_micro,key=lambda r:(r["pair_id"],r["variant_role"],r["micro_event_id"]))),
        "stop_loss_fingerprint":digest(summary["stop_loss_gates"])}
    sem["combined_semantic_fingerprint"] = digest(sem)
    require(sem == read_json(output / "n_frontend3b_semantic_output_manifest.json") and
            sem["combined_semantic_fingerprint"] == summary["semantic_output_fingerprint"], "semantic manifest mismatch")
    return {"persisted_content_recomputed":True,"source_binding_recomputed":True,
            "truth_and_denominators_recomputed":True,"history_and_ledger_recomputed":True}
