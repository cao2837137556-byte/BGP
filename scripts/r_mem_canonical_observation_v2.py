#!/usr/bin/env python3
"""Peer-aware canonical observation schema for R-MEM-1E.

The v2 contract preserves the peer address needed to distinguish an archive
overlap duplicate from a simultaneous observation emitted by another peer.
It deliberately keeps source provenance outside the semantic observation ID.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from run_r_mem1c_local_mrt_parser_smoke import derive_origin, safe_int


SCHEMA_VERSION = "canonical_observation_v2"
BASE_SEMANTIC_FIELDS = (
    "ts",
    "collector",
    "project",
    "type",
    "peer_asn",
    "prefix",
    "as_path",
    "origin_as",
    "origin_provenance",
    "communities",
    "next_hop",
)


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_communities(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        text = str(value).strip()
        items = text.split() if text else []
    return sorted(item for item in items if item)


def canonical_base_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in BASE_SEMANTIC_FIELDS:
        value = row.get(field)
        if hasattr(value, "as_py"):
            value = value.as_py()
        if field == "communities":
            value = normalize_communities(value)
        payload[field] = value
    return payload


def canonical_base_fingerprint(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            canonical_base_payload(row), sort_keys=True, default=str
        ).encode("utf-8")
    ).hexdigest()


def observation_id_from_base_fingerprint(
    base_fingerprint: str, peer_address: Any
) -> str | None:
    peer = normalize_text(peer_address)
    if peer is None:
        return None
    payload = {
        "base_fingerprint": base_fingerprint,
        "identity_basis": "peer_address",
        "identity_value": peer,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def canonical_observation_id(row: dict[str, Any]) -> str | None:
    return observation_id_from_base_fingerprint(
        canonical_base_fingerprint(row), row.get("peer_address")
    )


def element_to_row_v2(
    elem: Any,
    source: dict[str, Any],
    source_relative_path: str,
) -> dict[str, Any]:
    fields = elem.fields
    as_path = fields.get("as-path")
    origin_as, origin_provenance = derive_origin(as_path)
    row = {
        "ts": float(elem.time),
        "collector": str(source["collector"]),
        "project": str(source["project"]),
        "type": str(elem.type),
        "peer_asn": safe_int(getattr(elem, "peer_asn", None)),
        "peer_address": normalize_text(getattr(elem, "peer_address", None)),
        "prefix": fields.get("prefix"),
        "as_path": str(as_path) if as_path is not None else None,
        "origin_as": origin_as,
        "origin_provenance": origin_provenance,
        "communities": normalize_communities(fields.get("communities")),
        "next_hop": fields.get("next-hop"),
        "source_file": source_relative_path,
        "archive_timestamp_utc": source["archive_timestamp_utc"],
    }
    row["observation_id"] = canonical_observation_id(row)
    return row


def parquet_schema_v2():
    import pyarrow as pa

    return pa.schema(
        [
            ("ts", pa.float64()),
            ("collector", pa.string()),
            ("project", pa.string()),
            ("type", pa.string()),
            ("peer_asn", pa.int64()),
            ("peer_address", pa.string()),
            ("prefix", pa.string()),
            ("as_path", pa.string()),
            ("origin_as", pa.string()),
            ("origin_provenance", pa.string()),
            ("communities", pa.list_(pa.string())),
            ("next_hop", pa.string()),
            ("observation_id", pa.string()),
            ("source_file", pa.string()),
            ("archive_timestamp_utc", pa.string()),
        ]
    )


def schema_payload_v2() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "fields": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in parquet_schema_v2()
        ],
        "identity_contract": {
            "observation_id": "sha256(canonical base payload + peer_address)",
            "peer_address_required_for_deduplication": True,
            "source_file_excluded_from_observation_id": True,
            "archive_timestamp_excluded_from_observation_id": True,
            "missing_peer_address": "observation_id is null; row is not auto-deduplicable",
        },
        "truth_contract": {
            "attack_or_benign_truth_produced": False,
            "unlabeled_public_background_is_confirmed_benign": False,
        },
    }


def run_self_test() -> int:
    class FakeElement:
        time = 1712448899.0
        type = "A"
        peer_asn = 64500
        peer_address = "192.0.2.20"
        fields = {
            "prefix": "203.0.113.0/24",
            "as-path": "64500 64496",
            "communities": {"64500:2", "64500:1"},
            "next-hop": "192.0.2.1",
        }

    source = {
        "collector": "route-views.sg",
        "project": "routeviews",
        "archive_timestamp_utc": "2024-04-07T00:15:00Z",
    }
    first = element_to_row_v2(FakeElement(), source, "a.bz2")
    second = dict(first)
    second["source_file"] = "b.bz2"
    second["communities"] = ["64500:2", "64500:1"]
    second["observation_id"] = canonical_observation_id(second)
    assert first["communities"] == ["64500:1", "64500:2"]
    assert first["observation_id"] == second["observation_id"]
    different_peer = dict(first)
    different_peer["peer_address"] = "192.0.2.21"
    assert canonical_observation_id(different_peer) != first["observation_id"]
    missing_peer = dict(first)
    missing_peer["peer_address"] = None
    assert canonical_observation_id(missing_peer) is None
    print("self_test=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_self_test())
