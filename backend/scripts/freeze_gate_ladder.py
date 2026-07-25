"""Freeze the July 2026 legacy NNUE gate into a corpus-independent manifest.

This generator deliberately uses gate_ladder.py's existing probe-selection and
Stockfish-label semantics.  It writes the selected material probes, Spearman
parents, quiet children, and SF18 labels so later candidate decisions never
rescan a training corpus or regenerate labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import chess

import gate_ladder as legacy


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "gate_ladder_frozen_20260725.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_manifest() -> dict[str, object]:
    material = [
        {"fen": fen, "sf18_cp": score}
        for fen, score in legacy.find_queen_down_positions()
    ]
    parents = legacy.find_spearman_positions(legacy.N_POSITIONS)
    sf_cache = legacy.build_sf_cache()

    spearman = []
    for parent_index, ((parent_fen, children), expected_parent) in enumerate(
        zip(sf_cache, parents, strict=True), 1
    ):
        if parent_fen != expected_parent:
            raise RuntimeError(
                f"parent {parent_index} changed between selection and labeling"
            )

        board = chess.Board(parent_fen)
        moves = [
            move
            for move in board.legal_moves
            if not board.is_capture(move)
            and not board.gives_check(move)
            and not move.promotion
        ][: legacy.MAX_QUIET_PER_POS]
        if len(moves) != len(children):
            raise RuntimeError(
                f"parent {parent_index}: {len(moves)} moves != "
                f"{len(children)} labeled children"
            )

        frozen_children = []
        for move, (child_fen, sf18_cp) in zip(moves, children, strict=True):
            board.push(move)
            generated_fen = board.fen()
            board.pop()
            if generated_fen != child_fen:
                raise RuntimeError(
                    f"parent {parent_index} move {move.uci()}: child FEN changed"
                )
            frozen_children.append(
                {
                    "uci": move.uci(),
                    "fen": child_fen,
                    "sf18_cp": sf18_cp,
                }
            )

        spearman.append(
            {
                "parent_index": parent_index,
                "parent_fen": parent_fen,
                "children": frozen_children,
            }
        )

    parents_artifact = [
        {"parent_index": item["parent_index"], "fen": item["parent_fen"]}
        for item in spearman
    ]
    children_artifact = [
        {
            "parent_index": item["parent_index"],
            "uci": child["uci"],
            "fen": child["fen"],
        }
        for item in spearman
        for child in item["children"]
    ]
    labels_artifact = [
        {
            "parent_index": item["parent_index"],
            "uci": child["uci"],
            "sf18_cp": child["sf18_cp"],
        }
        for item in spearman
        for child in item["children"]
    ]

    legacy_script = Path(legacy.__file__).resolve()
    source_plain = legacy.SF18_DATA.resolve()
    stockfish = legacy.STOCKFISH.resolve()

    options = {
        "sf_depth": legacy.SF_DEPTH,
        "n_parent_positions": legacy.N_POSITIONS,
        "max_quiet_children_per_parent": legacy.MAX_QUIET_PER_POS,
        "stockfish_threads": 1,
        "stockfish_hash_mb": 64,
        "stockfish_ucinewgame_per_child": True,
        "stockfish_clear_hash_per_child": False,
        "material_scan_limit_lines": 2_000_000,
        "parent_scan_limit_lines": 5_000_000,
        "parent_filters": {
            "exactly_one_queen_each": True,
            "minimum_ply": 20,
            "absolute_training_score_max_cp": 200,
            "not_in_check": True,
            "minimum_quiet_children": 6,
        },
        "child_filters": {
            "quiet": True,
            "not_check": True,
            "not_promotion": True,
            "take_first_in_python_chess_iteration_order": 25,
        },
        "spearman_implementation": "double_argsort_no_tie_average",
        "aggregate": "unweighted_mean_of_parent_rhos",
    }

    return {
        "schema_version": 1,
        "gate_id": "pyro-phase-d-legacy-frozen-20260725",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Frozen companion to the July 2026 legacy Phase D gate. "
            "The dynamic legacy gate remains unchanged for historical comparison."
        ),
        "provenance": {
            "legacy_gate_script": str(legacy_script),
            "legacy_gate_script_sha256": sha256_file(legacy_script),
            "source_plain": str(source_plain),
            "source_plain_sha256": sha256_file(source_plain),
            "stockfish": str(stockfish),
            "stockfish_sha256": sha256_file(stockfish),
            "python_chess_version": chess.__version__,
        },
        "options": options,
        "expected_session1_anchor": {
            "raw_path": (
                "bullet/checkpoints/pyro-gpu-screlu/"
                "pyro-gpu-screlu-30/raw.bin"
            ),
            "raw_md5": "1d5fa710617d3aa2154e4f0d04b9f75d",
            "gate_a_pass": True,
            "gate_a_saturation_percent_rounded_1dp": 0.0,
            "gate_m_mean_ratio_rounded_2dp": 1.03,
            "rho_rounded_3dp": 0.213,
        },
        "artifacts_sha256": {
            "options": canonical_sha256(options),
            "material_probe_and_labels": canonical_sha256(material),
            "spearman_parents": canonical_sha256(parents_artifact),
            "spearman_children": canonical_sha256(children_artifact),
            "spearman_labels": canonical_sha256(labels_artifact),
            "spearman_combined": canonical_sha256(spearman),
        },
        "material": material,
        "spearman": spearman,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze gate_ladder.py probes and SF18 labels"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"REFUSING TO OVERWRITE frozen manifest: {output}")

    manifest = build_manifest()
    output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote frozen gate manifest: {output}")
    print(f"Manifest SHA256: {sha256_file(output)}")
    print(
        "Artifacts SHA256:\n"
        + json.dumps(manifest["artifacts_sha256"], indent=2, sort_keys=True)
    )


if __name__ == "__main__":
    main()
