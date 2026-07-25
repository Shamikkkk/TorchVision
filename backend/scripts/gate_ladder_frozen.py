"""Evaluate Bullet raw checkpoints against the frozen July 2026 Phase D gate.

Unlike gate_ladder.py, this companion performs no corpus scan and launches no
Stockfish process.  Every probe and SF18 label comes from the immutable JSON
manifest produced by freeze_gate_ladder.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import gate_ladder as legacy


HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "gate_ladder_frozen_20260725.json"


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_and_verify_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"unsupported manifest schema: {manifest.get('schema_version')}")

    spearman = manifest["spearman"]
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
    calculated = {
        "options": canonical_sha256(manifest["options"]),
        "material_probe_and_labels": canonical_sha256(manifest["material"]),
        "spearman_parents": canonical_sha256(parents_artifact),
        "spearman_children": canonical_sha256(children_artifact),
        "spearman_labels": canonical_sha256(labels_artifact),
        "spearman_combined": canonical_sha256(spearman),
    }
    if calculated != manifest["artifacts_sha256"]:
        raise ValueError(
            "frozen manifest artifact hash mismatch\n"
            f"expected={manifest['artifacts_sha256']}\n"
            f"actual={calculated}"
        )
    return manifest


def gate_m_frozen(
    net: legacy.Net, label: str, material: list[dict[str, object]]
) -> tuple[bool, float]:
    print(f"\n=== Gate M (frozen material pricing): {label} ===")
    ratios = []
    print(f"{'SF18 cp':>10} {'NNUE cp':>10} {'ratio':>7}")
    for record in material:
        fen = str(record["fen"])
        sf_cp = int(record["sf18_cp"])
        nn_cp = net.eval_cp(fen)
        ratio = nn_cp / sf_cp
        ratios.append(ratio)
        print(f"{sf_cp:>+10d} {nn_cp:>+10.1f} {ratio:>7.2f}  {fen}")
    mean_ratio = float(np.mean(ratios))
    ok = mean_ratio >= 0.5
    print(
        f"GATE M: {'PASS' if ok else 'FAIL'} — mean NNUE/SF18 ratio "
        f"{mean_ratio:.2f} (>=0.50 = queen deficit priced)"
    )
    return ok, mean_ratio


def gate_s_frozen(
    net: legacy.Net, label: str, spearman: list[dict[str, object]]
) -> tuple[float, list[float]]:
    print(f"\n=== Gate S (frozen Spearman): {label} ===")
    rhos = []
    for item in spearman:
        children = item["children"]
        nnue_evals = [-net.eval_cp(str(child["fen"])) for child in children]
        sf_evals = [-int(child["sf18_cp"]) for child in children]
        rho = legacy.spearman(nnue_evals, sf_evals)
        rhos.append(rho)
        print(
            f"  pos {int(item['parent_index']):<3} "
            f"n={len(children):<3} rho={rho:+.3f}"
        )
    values = np.asarray(rhos, dtype=float)
    mean_rho = float(values.mean())
    print(
        f"Mean rho: {mean_rho:+.3f}  median {np.median(values):+.3f}  "
        f"min {values.min():+.3f}  max {values.max():+.3f}"
    )
    return mean_rho, rhos


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen Phase D gate")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw", action="append", required=True)
    parser.add_argument("--hidden", action="append", type=int, required=True)
    parser.add_argument(
        "--activation",
        action="append",
        required=True,
        choices=["crelu", "screlu"],
    )
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument(
        "--verify-session1-anchor",
        action="store_true",
        help="Require the single supplied raw file to reproduce the frozen anchor",
    )
    args = parser.parse_args()

    if not (
        len(args.raw)
        == len(args.hidden)
        == len(args.activation)
        == len(args.label)
    ):
        parser.error("--raw/--hidden/--activation/--label counts must match")

    manifest_path = args.manifest.resolve()
    manifest = load_and_verify_manifest(manifest_path)
    print(f"Frozen manifest: {manifest_path}")
    print(f"Manifest SHA256: {file_digest(manifest_path, 'sha256')}")
    print(
        "Artifact hashes verified: "
        + json.dumps(manifest["artifacts_sha256"], sort_keys=True)
    )

    summary = []
    for raw_arg, hidden, activation, label in zip(
        args.raw, args.hidden, args.activation, args.label, strict=True
    ):
        raw_path = Path(raw_arg).resolve()
        print(
            f"\nLoading {label}: {raw_path} "
            f"(hidden={hidden}, {activation}, md5={file_digest(raw_path, 'md5')})"
        )
        net = legacy.Net(raw_path, hidden, activation)
        a_ok, a_sat = legacy.gate_a(net, label)
        m_ok, m_ratio = gate_m_frozen(net, label, manifest["material"])
        rho, parent_rhos = gate_s_frozen(net, label, manifest["spearman"])
        summary.append(
            {
                "label": label,
                "raw_path": str(raw_path),
                "raw_md5": file_digest(raw_path, "md5"),
                "gate_a_pass": a_ok,
                "gate_a_saturation": a_sat,
                "gate_m_pass": m_ok,
                "gate_m_ratio": m_ratio,
                "rho": rho,
                "parent_rhos": parent_rhos,
            }
        )

    print("\n" + "=" * 78)
    print("FROZEN GATE SUMMARY")
    print("=" * 78)
    print(f"{'candidate':<28} {'GateA':>6} {'sat%':>6} {'GateM':>6} {'M-ratio':>8} {'rho':>7}")
    for item in summary:
        print(
            f"{item['label']:<28} "
            f"{'PASS' if item['gate_a_pass'] else 'FAIL':>6} "
            f"{100 * item['gate_a_saturation']:>5.1f}% "
            f"{'PASS' if item['gate_m_pass'] else 'FAIL':>6} "
            f"{item['gate_m_ratio']:>8.2f} {item['rho']:>+7.3f}"
        )

    if args.verify_session1_anchor:
        if len(summary) != 1:
            parser.error("--verify-session1-anchor requires exactly one candidate")
        expected = manifest["expected_session1_anchor"]
        actual = summary[0]
        checks = {
            "raw_md5": actual["raw_md5"].lower() == expected["raw_md5"].lower(),
            "gate_a_pass": actual["gate_a_pass"] is expected["gate_a_pass"],
            "gate_a_saturation_1dp": (
                round(100 * actual["gate_a_saturation"], 1)
                == expected["gate_a_saturation_percent_rounded_1dp"]
            ),
            "gate_m_ratio_2dp": (
                round(actual["gate_m_ratio"], 2)
                == expected["gate_m_mean_ratio_rounded_2dp"]
            ),
            "rho_3dp": round(actual["rho"], 3) == expected["rho_rounded_3dp"],
        }
        print("\nSESSION-1 ANCHOR CHECKS")
        for name, passed in checks.items():
            print(f"  {name:<28} {'PASS' if passed else 'FAIL'}")
        if not all(checks.values()):
            raise SystemExit("FROZEN GATE ANCHOR REPRODUCTION: FAIL")
        print("FROZEN GATE ANCHOR REPRODUCTION: PASS")

    print("\nRESULT_JSON")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
