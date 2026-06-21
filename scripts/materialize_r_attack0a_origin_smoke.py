import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


RAW_COLUMNS = [
    "ts",
    "collector",
    "type",
    "peer_asn",
    "prefix",
    "as_path",
    "communities",
    "next_hop",
]
CHUNK_RE = re.compile(
    r"updates__(?P<start>\d{2}-\d{2}-\d{2})__(?P<end>\d{2}-\d{2}-\d{2})\.parquet$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize the controlled R-ATTACK-0A origin smoke as a derived raw run."
    )
    parser.add_argument("--config", default="configs/r_attack0a_origin_smoke_v01.yaml")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-root", default="")
    parser.add_argument("--derived-run-root", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def rel_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return data


def parse_utc(value: str) -> float:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(timezone.utc).timestamp()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def raw_files(run_root: Path) -> list[Path]:
    files = []
    for path in run_root.glob("collector=*/date=*/updates__*.parquet"):
        if "__rel" not in path.name:
            files.append(path)
    return sorted(files, key=lambda item: item.as_posix())


def chunk_bounds(path: Path) -> tuple[float, float]:
    match = CHUNK_RE.fullmatch(path.name)
    if match is None:
        raise ValueError(f"unexpected raw chunk name: {path}")
    date_part = next(part.split("=", 1)[1] for part in path.parts if part.startswith("date="))
    start = datetime.strptime(
        f"{date_part} {match.group('start').replace('-', ':')}", "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=timezone.utc)
    end = datetime.strptime(
        f"{date_part} {match.group('end').replace('-', ':')}", "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=timezone.utc)
    if end <= start:
        end += timedelta(days=1)
    return start.timestamp(), end.timestamp()


def collector_from_path(path: Path) -> str:
    return next(part.split("=", 1)[1] for part in path.parts if part.startswith("collector="))


def load_templates(files: list[Path], prefixes: set[str]) -> pd.DataFrame:
    rows = []
    for path in files:
        frame = pd.read_parquet(path, columns=RAW_COLUMNS)
        selected = frame[
            frame["prefix"].astype(str).isin(prefixes)
            & frame["type"].astype(str).str.upper().eq("A")
            & frame["as_path"].notna()
        ].copy()
        if selected.empty:
            continue
        selected["_source_path"] = str(path.resolve())
        rows.append(selected)
    if not rows:
        raise ValueError("no legitimate raw templates found for configured victim prefixes")
    return pd.concat(rows, ignore_index=True)


def parse_path(value: Any) -> list[int]:
    return [int(token) for token in re.findall(r"\d+", str(value))]


def clean_path(values: list[int]) -> list[int]:
    result = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result


def select_template(
    templates: pd.DataFrame,
    prefix: str,
    collector: str,
    legitimate_origin: int,
    target_ts: float,
) -> pd.Series:
    subset = templates[
        templates["prefix"].astype(str).eq(prefix)
        & templates["collector"].astype(str).eq(collector)
    ].copy()
    subset["_parsed_path"] = subset["as_path"].map(parse_path)
    subset = subset[subset["_parsed_path"].map(lambda path: bool(path) and path[-1] == legitimate_origin)]
    if subset.empty:
        raise ValueError(
            f"no legitimate template for prefix={prefix}, collector={collector}, origin={legitimate_origin}"
        )
    subset["_distance"] = (pd.to_numeric(subset["ts"], errors="coerce") - target_ts).abs()
    return subset.sort_values(["_distance", "ts"]).iloc[0]


def find_target_chunk(files: list[Path], collector: str, ts: float) -> Path:
    matches = []
    for path in files:
        if collector_from_path(path) != collector:
            continue
        start, end = chunk_bounds(path)
        if start <= ts < end:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(f"expected one target chunk for collector={collector}, ts={ts}; got {matches}")
    return matches[0]


def build_attack_path(
    legitimate_path: list[int], subtype: str, legitimate_origin: int, attacker_as: int
) -> list[int]:
    path = clean_path(legitimate_path)
    if not path or path[-1] != legitimate_origin:
        raise ValueError("template path does not end in configured legitimate origin")
    if attacker_as in path:
        raise ValueError(f"synthetic attacker ASN already occurs in legitimate path: {attacker_as}")
    if subtype == "exact_prefix_origin_hijack":
        return [*path[:-1], attacker_as]
    if subtype == "forged_origin_hijack":
        return [*path[:-1], attacker_as, legitimate_origin]
    raise ValueError(f"unsupported R-ATTACK-0A subtype: {subtype}")


def record_id(scenario_id: str, phase_id: str, collector: str, ts: float) -> str:
    payload = f"{scenario_id}|{phase_id}|{collector}|{ts:.3f}"
    return "rawinj_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def prepare_injections(
    config: dict[str, Any], files: list[Path], templates: pd.DataFrame, repo_root: Path
) -> tuple[dict[Path, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    collectors = [str(value) for value in config["expected_collectors"]]
    by_chunk: dict[Path, list[dict[str, Any]]] = {}
    labels = []
    scenario_rows = []

    for scenario in config["scenarios"]:
        prefix = str(scenario["victim_prefix"])
        legitimate_origin = int(scenario["legitimate_origin_as"])
        attacker_as = int(scenario["attacker_as"])
        subtype = str(scenario["attack_subtype"])
        all_phase_ts = [
            parse_utc(timestamp)
            for phase in scenario["phase_schedule"].values()
            for timestamp in phase["timestamps"]
        ]
        template_target_ts = min(all_phase_ts)
        collector_templates = {
            collector: select_template(
                templates, prefix, collector, legitimate_origin, template_target_ts
            )
            for collector in collectors
        }
        scenario_rows.append(
            {
                **scenario,
                "source_background_run_id": config["source_background_run_id"],
                "derived_run_id": config["derived_run_id"],
                "collector_set_id": config["collector_set_id"],
                "expected_collectors": collectors,
                "evidence_snapshot_binding": config["evidence_snapshot_binding"],
                "label_source": "controlled_injection_metadata",
                "truth_confidence_tier": "exact",
            }
        )

        for phase_id, phase in scenario["phase_schedule"].items():
            for timestamp in phase["timestamps"]:
                ts = parse_utc(timestamp)
                for collector in collectors:
                    template = collector_templates[collector]
                    legitimate_path = parse_path(template["as_path"])
                    is_attack = phase_id == "attack_launch"
                    emitted_path = (
                        build_attack_path(
                            legitimate_path, subtype, legitimate_origin, attacker_as
                        )
                        if is_attack
                        else clean_path(legitimate_path)
                    )
                    attack_role = (
                        "attacker_announce"
                        if is_attack
                        else ("recovery_announce" if phase_id == "recovery" else "legitimate_announce")
                    )
                    target = find_target_chunk(files, collector, ts)
                    raw_id = record_id(scenario["scenario_id"], phase_id, collector, ts)
                    raw_row = {
                        "ts": float(ts),
                        "collector": collector,
                        "type": "A",
                        "peer_asn": int(template["peer_asn"]),
                        "prefix": prefix,
                        "as_path": " ".join(str(asn) for asn in emitted_path),
                        "communities": [] if is_attack else template["communities"],
                        "next_hop": template["next_hop"],
                    }
                    by_chunk.setdefault(target, []).append(raw_row)
                    labels.append(
                        {
                            "raw_record_id": raw_id,
                            "scenario_id": scenario["scenario_id"],
                            "phase_id": phase_id,
                            "attack_role": attack_role,
                            "is_injected": True,
                            "is_attack_member": bool(is_attack),
                            "raw_event_eligible": True,
                            "raw_label_source": "controlled_injection_metadata",
                            "collector": collector,
                            "ts": float(ts),
                            "prefix": prefix,
                            "as_path": raw_row["as_path"],
                            "origin_as": emitted_path[-1],
                            "legitimate_origin_as": legitimate_origin,
                            "attacker_as": attacker_as,
                            "attack_subtype": subtype,
                            "primary_family": scenario["primary_family"],
                            "adversarial_variant": scenario["adversarial_variant"],
                            "expected_visibility_class": scenario["expected_visibility_class"],
                            "source_template_path": rel_path(
                                Path(str(template["_source_path"])), repo_root
                            ),
                            "target_chunk": rel_path(target, repo_root),
                            "community_semantics": (
                                "explicit_empty_for_attack_smoke"
                                if is_attack
                                else "copied_from_legitimate_template"
                            ),
                        }
                    )
    return by_chunk, labels, scenario_rows


def assert_output_ready(derived_root: Path, output_dir: Path, overwrite: bool) -> None:
    existing = []
    if derived_root.exists() and any(derived_root.iterdir()):
        existing.append(derived_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        existing.append(output_dir)
    if existing and not overwrite:
        raise FileExistsError(
            "outputs exist; pass --overwrite to replace: " + ", ".join(str(path) for path in existing)
        )
    if overwrite:
        for path in existing:
            shutil.rmtree(path)


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    config = read_config(config_path)
    source_root = (
        Path(args.source_run_root).resolve()
        if args.source_run_root
        else repo_root / "data" / "runs" / str(config["source_background_run_id"])
    )
    derived_root = (
        Path(args.derived_run_root).resolve()
        if args.derived_run_root
        else repo_root / "data" / "runs" / str(config["derived_run_id"])
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else repo_root / "outputs" / "r_attack_0a" / str(config["derived_run_id"])
    )

    if source_root.resolve() == derived_root.resolve():
        raise ValueError("derived run root must differ from source background run root")
    if not source_root.exists():
        raise FileNotFoundError(source_root)
    assert_output_ready(derived_root, output_dir, args.overwrite)

    files = raw_files(source_root)
    if len(files) != 144:
        raise ValueError(f"expected 144 source raw chunks, found {len(files)}")
    prefixes = {str(item["victim_prefix"]) for item in config["scenarios"]}
    templates = load_templates(files, prefixes)
    by_chunk, labels, scenario_rows = prepare_injections(config, files, templates, repo_root)

    derived_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    source_rows = 0
    derived_rows = 0
    for source in files:
        relative = source.relative_to(source_root)
        target = derived_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source_count = int(pd.read_parquet(source, columns=["ts"]).shape[0])
        source_rows += source_count
        injected = by_chunk.get(source, [])
        if injected:
            frame = pd.read_parquet(source)
            injection_frame = pd.DataFrame(injected, columns=frame.columns)
            combined = pd.concat([frame, injection_frame], ignore_index=True)
            combined = combined.sort_values(["ts", "collector", "prefix", "as_path"], na_position="last")
            combined.to_parquet(target, index=False)
            mode = "rewritten_with_injection"
            output_count = int(len(combined))
            digest = sha256_file(target)
        else:
            os.link(source, target)
            mode = "hardlink_unchanged"
            output_count = source_count
            digest = ""
        derived_rows += output_count
        manifest.append(
            {
                "source_path": rel_path(source, repo_root),
                "derived_path": rel_path(target, repo_root),
                "materialization_mode": mode,
                "source_rows": source_count,
                "injected_rows": len(injected),
                "derived_rows": output_count,
                "derived_sha256_if_rewritten": digest,
            }
        )

    labels_df = pd.DataFrame(labels)
    smoke_raw_root = output_dir / "smoke_raw"
    smoke_raw_root.mkdir(parents=True, exist_ok=True)
    smoke_chunk_count = 0
    for source in sorted(by_chunk, key=lambda item: item.as_posix()):
        derived_source = derived_root / source.relative_to(source_root)
        smoke_target = smoke_raw_root / source.relative_to(source_root)
        smoke_target.parent.mkdir(parents=True, exist_ok=True)
        os.link(derived_source, smoke_target)
        smoke_chunk_count += 1

    labels_df.to_parquet(output_dir / "injected_raw_truth.parquet", index=False)
    labels_df.to_csv(output_dir / "injected_raw_truth.csv", index=False)
    pd.DataFrame(manifest).to_csv(output_dir / "derived_raw_manifest.csv", index=False)
    (output_dir / "scenario_registry.json").write_text(
        json.dumps(scenario_rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    summary = {
        "phase": "R-ATTACK-0A",
        "config": rel_path(config_path, repo_root),
        "source_background_run_id": config["source_background_run_id"],
        "derived_run_id": config["derived_run_id"],
        "source_raw_chunks": len(files),
        "rewritten_chunks": len(by_chunk),
        "hardlinked_chunks": len(files) - len(by_chunk),
        "source_raw_rows": source_rows,
        "injected_raw_rows": int(len(labels_df)),
        "injected_attack_rows": int(labels_df["is_attack_member"].sum()),
        "injected_control_rows": int((~labels_df["is_attack_member"]).sum()),
        "derived_raw_rows": derived_rows,
        "scenario_count": len(scenario_rows),
        "scenario_ids": [row["scenario_id"] for row in scenario_rows],
        "smoke_raw_root": rel_path(smoke_raw_root, repo_root),
        "smoke_raw_chunks": smoke_chunk_count,
        "smoke_scope": (
            "Only rewritten chunks containing controlled records. This validates "
            "raw admission and attack propagation, not full-window workload."
        ),
        "scientific_limits": config["scientific_limits"],
        "input_immutable": True,
        "truth_columns_added_to_raw": False,
        "next_step": (
            "build smoke events from smoke_raw, then candidates against the immutable "
            "clean baseline; full 6h replay is gated on smoke QA"
        ),
    }
    (output_dir / "materialization_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
