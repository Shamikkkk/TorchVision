# SCReLU-512 inference verification

Date: 2026-07-25

Branch: `feat/screlu-512-inference`

Base commit: `34cad65873b3ad3c8e93df69e8684f14fad0fe1c`

## Pre-committed prediction

The SCReLU-512 Rust path should match an independent implementation of Bullet's
quantized integer arithmetic exactly on every raw accumulator element and final
centipawn result. The `--no-nnue` bestmove transcript should remain
byte-identical to the pre-branch binary. Any mismatch stops the task before
game testing.

Result: **held**. No SPRT or other game match was run.

## Arithmetic derivation

Sources:

- `backend/scripts/bullet_port/pyro_v2_screlu512.rs`: `HIDDEN_SIZE=512`,
  `SCALE=400`, `QA=255`, `QB=64`, SCReLU graph, and the four save formats.
- `bullet/examples/simple.rs`: the reference quantized SCReLU forward pass and
  its two distinct integer divisions.
- `bullet/crates/trainer/src/model/weights.rs`: `SavedFormat::round()` and
  quantization implementation.

The exact integer forward pass is:

```text
q   = clamp(accumulator, 0, QA)
sum = Σ(q² * l1_weight)                  # signed i64 accumulation
sum = sum / QA                           # truncation toward zero
sum = sum + l1_bias
cp  = sum * SCALE / (QA * QB)            # truncation toward zero
```

Constants:

```text
QA          = 255
QB          = 64
SCALE       = 400
HIDDEN_SIZE = 512
```

Bullet serializes the tensors as:

```text
l0w: round(float * QA)       -> i16
l0b: round(float * QA)       -> i16
l1w: round(float * QB)       -> i16
l1b: round(float * QA * QB)  -> i16
```

`q²*l1_weight` therefore has scale `QA²*QB`. The first `/QA` reduces it
to `QA*QB`, exactly matching the serialized output-bias scale. The final
`/(QA*QB)` restores the network output scale before applying `SCALE`.

The exact champion's original Bullet artifact was also available:

```text
C:\torch_data\phase_d_rung_b\run1\checkpoints\pyro-gpu-screlu\pyro-gpu-screlu-30\quantised.bin
SHA-256 69c839a1b545343a13200c916d4d042b90ef6a9fc1baab5ef7d711cee1c51da1
```

The independently generated v2 payload is byte-identical to all 789,506
meaningful bytes in that file. Bullet's remaining 62 bytes are its documented
64-byte alignment pattern (`bullet...`) and are deliberately excluded from the
versioned engine file. This directly verifies both the tensor order and all four
save-format quantization multipliers.

The two divisions are deliberately not merged. A Rust unit-test vector produces
5 cp with the required ordering and 4 cp with the algebraically merged ordering.

## Versioned activation-aware file

The new format is NNUE version 2 with a 32-byte little-endian header:

```text
magic       "NNUE"
version     2
activation  2  (SCReLU)
input       768
hidden      512
QA          255
QB          64
SCALE       400
```

The loader validates every header field and the exact file length before reading
weights. The engine now exits with code 2 when a present NNUE file is rejected;
it cannot silently fall back to PST after finding an incompatible net.

Fail-closed checks:

- A copied v1 CReLU-256 live net beside the candidate was rejected at runtime:
  `unsupported NNUE version 1 (expected 2: SCReLU-512)`; exit code 2.
- Rust tests reject activation ID 1 and hidden width 256.
- The legacy v1 reader requires version 1, so a version-2 SCReLU-512 file cannot
  be interpreted as a v1 CReLU-256 payload. A reverse runtime check with copied
  files reported `NNUE not found, using PST`, confirming the legacy binary did
  not load the v2 net. The branch binary is stricter: a present rejected net is
  fatal rather than a fallback.
- A valid v2 SCReLU-512 net loaded successfully in the candidate; exit code 0.

## Rust-vs-Python agreement

Champion raw input:

```text
C:\torch_data\phase_d_champion\pyro_v2_screlu512_raw.bin
SHA-256 50e9eb4c1a7c6507d3b77562adde859e3eeb1c7d2efe4e838faabfc292e64184
```

Frozen set:

```text
backend/scripts/nnue_screlu512_positions.tsv
SHA-256 bb6cd52322d47369bd35926cfe4bd7d2dac8412e349207f91d5089d2c8115cd3
10,000 unique FENs
5,000 white to move / 5,000 black to move
```

Coverage:

| Category | Cases |
|---|---:|
| Natural v2-corpus positions | 8,000 |
| Queen-promotion material | 240 |
| Underpromotion material (rook/bishop/knight) | 360 |
| Multiple-queen/unusual material | 400 |
| Low-material/endgame | 500 |
| Selected near accumulator 0 | 125 |
| Selected near accumulator QA | 125 |
| Selected below accumulator 0 | 125 |
| Selected above accumulator QA | 125 |

The verifier rejects duplicate or invalid FENs and checks the category semantics,
not only the labels. The underpromotion subset covers knight, bishop, and rook
material (149, 162, and 165 cases respectively; counts overlap where a position
contains more than one type). Every selected boundary FEN satisfies its claimed
accumulator condition under the quantized champion.

For each FEN, the independent Python reference reconstructed both 512-element
raw accumulators directly from the quantized feature-transformer weights. The
Rust verifier independently parsed the FEN, built both accumulators, and ran the
engine evaluation path.

Result:

```text
Cases                    10,000
Raw accumulators exact   10,000 / 10,000
Final cp exact           10,000 / 10,000
Mismatches               0
```

Across the full set, 10,000 positions contained an accumulator element near 0,
6,482 near QA, 10,000 below 0, and 9,817 above QA. These counts overlap; they
confirm that clipping is exercised broadly in addition to the four selected
boundary categories.

Synthetic SCReLU boundary cases passed in both Rust and Python:

```text
input      -100000  -1  0  1  254    255    256    100000
q² output         0   0  0  1  64516  65025  65025  65025
result       8 / 8 exact
```

The complete machine-readable report is
`C:\torch_data\phase_d_inference\agreement_report.json`.

## `--no-nnue` no-op proof

Both binaries were run one process per position, with `Threads=1`, search depth
8, and `--no-nnue`.

Baseline binary:

```text
C:\torch_data\phase_d_inference\baseline\pyro.exe
SHA-256 e9fad8a7be642ccb4beb0f356fccab555e11bde0b49ffe14d4bf33688d154a00
```

Candidate binary:

```text
C:\torch_data\phase_d_inference\screlu512_target\release\pyro.exe
SHA-256 6a768a34b02ea6eeaa73cd0f79ae8318f27f1ae7cec47015ef8e46664fd3503e
```

Baseline transcript:

```text
startpos	d2d4
after_1e4	e7e5
italian	g8f6
french	b1c3
sicilian	e7e6
kgambit	e5f4
kid	e2e4
dragon	f1c4
greek_gift_attack	c3d5
king_attack_pos	c3d5
```

Candidate transcript:

```text
startpos	d2d4
after_1e4	e7e5
italian	g8f6
french	b1c3
sicilian	e7e6
kgambit	e5f4
kid	e2e4
dragon	f1c4
greek_gift_attack	c3d5
king_attack_pos	c3d5
```

Both transcript SHA-256 hashes are
`6bb6f5a09d92e113969f85e44dff8c78159513b78bb89664e6dd369927d7d0dc`.
The bestmove transcripts are byte-identical.

## Isolation and integrity

The candidate used the separate Cargo target directory:

```text
C:\torch_data\phase_d_inference\screlu512_target
```

The versioned champion net lives only beside that candidate:

```text
C:\torch_data\phase_d_inference\screlu512_target\release\pyro.nnue
bytes   789,538
SHA-256 a06cfebd7c22d0b45f08ba94a276fd2a7cf8b3cd76c54dd308b2eeaa1a579591
MD5     9f01010bfe8b41193f77a9fad88abd56
```

Neither live net was overwritten:

```text
engine/pyro.nnue                 MD5 23bfcd331411b8b9c6a05191d42caef5
engine/target/release/pyro.nnue  MD5 23bfcd331411b8b9c6a05191d42caef5
```

The default `engine/target/release/pyro.exe` also retained the pre-branch
SHA-256
`e9fad8a7be642ccb4beb0f356fccab555e11bde0b49ffe14d4bf33688d154a00`.
No live artifact was changed, no branch was merged, and no SPRT was started.
