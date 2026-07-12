# Bullet GPU trainer port (local additions to the bullet submodule)

bullet is pinned to `cebc78a0`; the files here are our local additions —
they live only in the submodule's working tree, which the pin does NOT
cover, so this directory is the durable copy.

## Restore after a fresh clone

1. Copy `pyro.rs`, `pyro_gpu_smoke.rs`, `pyro_gpu_512.rs`, and
   `pyro_gpu_screlu.rs` into `bullet/examples/`.
2. Append the blocks in `Cargo.toml.examples-snippet` to
   `bullet/crates/bullet_lib/Cargo.toml`.
3. Build (from `bullet/`):

   ```bash
   cargo build --release --package bullet_lib --example pyro --example pyro_gpu_smoke --example pyro_gpu_512 --example pyro_gpu_screlu --features cuda
   ```

Requires the CUDA 13.2 toolkit (`CUDA_PATH` set) + NVIDIA driver >= r595
(610.62 validated on the RTX 3050, July 12, 2026). At bullet main there are
no default features — a no-feature build gives the MockGpu test device, so
`--features cuda` is mandatory.

- `pyro.rs` — full trainer (net `pyro-gpu`, SB30, HIDDEN=256, CReLU,
  batch 16384, data `C:/torch_data/selfplay_sf18_d12.data`). Full run
  ~6 min on the 3050 (~1.5-4M pos/s).
- `pyro_gpu_smoke.rs` — 1-superbatch smoke variant, writes only to
  `checkpoints/pyro-gpu-smoke`.
- `pyro_gpu_512.rs` — capacity-ladder Candidate A (July 12, 2026):
  HIDDEN=512, otherwise expE config. Writes to `checkpoints/pyro-gpu-512`.
- `pyro_gpu_screlu.rs` — capacity-ladder Candidate B: SCReLU activation,
  otherwise expE config. Writes to `checkpoints/pyro-gpu-screlu`.
  (Neither net is engine-loadable as-is: nnue.rs is 256-wide CReLU.)
- `pyro_gpu_wdl01/03/05.rs` — WDL ladder (session 2a, July 12, 2026):
  SCReLU base + ConstantWDL 0.1/0.3/0.5. Own checkpoints/ dirs.
- `pyro_gpu_wdl01_crelu.rs` — D4 control: CReLU at WDL 0.1 (completes the
  activation x WDL 2x2). Writes to `checkpoints/pyro-gpu-wdl01-crelu`.
- `pyro.rs.pre-port` — the pre-port (cudarc-era, expE) trainer, kept for
  reference; it exists nowhere in git history besides this copy.
