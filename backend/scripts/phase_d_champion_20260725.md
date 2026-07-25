# Phase D champion staging record — July 25, 2026

## Designation

- Architecture: `(768 → 512)×2 → 1`, SCReLU
- Training corpus: `C:/torch_data/selfplay_v2_sf18.data` (full v2 corpus)
- Objective: eval-only, `ConstantWDL 0.0`
- Schedule: 1,221 batches × 30 superbatches = 36,630 updates; batch 16,384;
  600,145,920 positions consumed; seed 198273612; cosine `1e-3 → 1e-5`
- Selected checkpoint: rung (b), matched-pair run 1, final SB30 `raw.bin`
- Frozen-gate result: rho `+0.623487` (pair mean `+0.623564`)
- Status: SPRT-eligible; not inference-verified, SPRT-validated, style-validated,
  or shipped

## Durable artifact

- Path: `C:/torch_data/phase_d_champion/pyro_v2_screlu512_raw.bin`
- Bytes: `1,579,012`
- SHA-256: `50e9eb4c1a7c6507d3b77562adde859e3eeb1c7d2efe4e838faabfc292e64184`
- MD5: `56c14d958057aa23f16103c15b911ec6`
- Source: `C:/torch_data/phase_d_rung_b/run1/checkpoints/pyro-gpu-screlu/pyro-gpu-screlu-30/raw.bin`

This is the only net designated for the SCReLU-512 inference block. It is staged
outside every live-engine load path. The two live `pyro.nnue` files remained MD5
`23bfcd331411b8b9c6a05191d42caef5` when this record was created.

The frozen gate manifest used for the decision is
`backend/scripts/gate_ladder_frozen_20260725.json`, SHA-256
`3479ac0dd90c85447d3ef2bbb32fef56c888cdfc54bb130602cc1cf6119b0046`.

See `HISTORY.md`, “Phase D training ladder on v2 corpus — SCReLU-512 champion
(July 25, 2026),” for the complete ladder record and verdicts.
