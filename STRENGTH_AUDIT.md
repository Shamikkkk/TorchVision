# STRENGTH AUDIT — Pyro engine, July 26, 2026

Audit-only snapshot of `engine/src/` (search.rs 1850 lines, nnue.rs 639, movegen.rs 940,
board.rs 394, main.rs 275) against the canonical strong-engine feature set. No code was
changed. Framing: **strength = NPS × pruning quality**; each effective ply ≈ +50-70 Elo,
each 2× NPS ≈ +1 ply. Pyro is deficient on BOTH axes, which is good news: two independent
lanes of headroom, each gated by our existing SPRT + style methodology.

**Measured baseline (this audit, single thread, midgame FEN, 300k nodes):**
- NNUE path: **~106k nps** · PeSTO path: **~242k nps** → the current NNUE integration
  costs ~56% of total search time.
- No `bench` command exists; `info` lines emit neither `nodes` nor `nps` (worth adding
  for future measurement hygiene).

---

## 1. FEATURE MATRIX

### A) Search — core

| Feature | Status | Evidence / notes |
|---|---|---|
| Transposition table | **PARTIAL** | `search.rs:55-205`. 1M entries / **16MB fixed** — no UCI `Hash` option (main.rs:90 exposes only `Threads`). XOR-checksum lockless (correct Lazy-SMP pattern). Depth-or-newer-gen replacement (`search.rs:183-189`). Mate-score ply adjustment present (`search.rs:208-227`). **Weaknesses:** scores only trusted from the *current generation* (`search.rs:1221` — cross-iteration cutoffs discarded); TT cutoffs return hard `beta`/`alpha` not the entry score (`search.rs:1225-1230`); **no TT probe/store in quiescence at all**. |
| Iterative deepening + aspiration | **PRESENT/PARTIAL** | `search.rs:1596-1703`. Aspiration ±50cp (`TUNE_ASPIRATION_DELTA`), but fail-high/low widens **straight to ±INF** (`search.rs:1668-1682`) — no gradual widening. |
| PVS | **PRESENT** | `search.rs:1382-1403`: first move full window, rest null-window + re-search. Genuine PVS. |
| Quiescence | **PARTIAL** | `search.rs:1095-1161`. Captures only, SEE < 0 pruned (`:1124`). **Missing:** TT interaction, delta pruning, check evasions/quiet checks, and it calls full `generate_moves` then filters (`:1098` — full movegen cost per QS node, incl. a mate/stalemate legality pass that is only needed when in check). Stand-pat = **full NNUE rebuild** (`:1109`). |
| Null-move pruning | **PARTIAL** | `search.rs:1246-1253`. Static R=2, no depth-scaled R (strong engines: R = 3 + depth/3 + eval-margin term), no verification search, disabled below 10 total pieces (crude zugzwang guard; standard is "STM has a non-pawn piece"). |
| LMR | **PARTIAL — barely** | `search.rs:1390-1394`. Fixed reduction of **exactly 1 ply** (`depth-2`), only for move_index > 3, quiet, non-killer, not-in-check. **No log formula** (`R ≈ 0.77 + ln(d)·ln(m)/2.36` class), no history/PV/improving adjustments. This is the single biggest search gap: real LMR reduces late moves by 3-5 plies at depth 12+. |
| RFP / static NMP | **ABSENT** | No `eval - margin·depth ≥ beta` fast-fail anywhere. |
| LMP + improving | **ABSENT** | Parked June 2026 ("catastrophic without IID" vs PeSTO — see §4 for re-open case). No `improving` tracking exists (no eval stack). |
| Futility pruning | **PRESENT** | `search.rs:1328-1345, 1366-1368`. Depth ≤ 2, margins 100/300, sane mate guards. Cost bug: computes the (full-rebuild) static eval even when depth > 2 short-circuits... actually gated correctly, but each check costs a full NNUE rebuild at d≤2 nodes. |
| Razoring | **ABSENT** | — |
| IIR | **ABSENT** (IID dormant) | IID exists behind `IID_ENABLE=false` (`search.rs:1259-1262`, measured neutral vs PeSTO). Modern replacement IIR (just `depth -= 1` on no-TT-move) is simpler and cheaper. |
| SEE | **PRESENT** | `search.rs:935-985`. Correct swap algorithm. **Used only in QS filtering and move ordering** — no SEE pruning of losing captures/quiets in the main search (PVS SEE pruning is standard: skip quiets with SEE < -50·depth, captures < -90·depth at shallow depth). |
| Singular extensions | **PRESENT (basic)** | `search.rs:1264-1305`. TT-gated, IID-poisoning fix in place. No multicut (se_best ≥ se_beta could return beta), no negative/double extensions. |
| Check extensions | **PRESENT** | `search.rs:1243`. |
| History pruning | **ABSENT** | History exists (below) but never prunes/reduces. |

### B) Move ordering

| Feature | Status | Evidence / notes |
|---|---|---|
| TT move first | **PRESENT** | `search.rs:1011-1016` (score 100k). |
| MVV-LVA | **PRESENT** | `search.rs:1017-1029`. |
| Good/bad capture split by SEE | **PRESENT** | `search.rs:1025-1028` (SEE<0 → below killers). |
| Killers | **PRESENT** | 2 slots/ply, `search.rs:1061-1072`. |
| Butterfly history + gravity + malus | **PRESENT** | `search.rs:888-907` (gravity formula), malus for non-cutting quiets `search.rs:1415-1419`. Cap 4,000 is very low (standard ~16k with larger bonuses). |
| Continuation history (CMH/FMH) | **ABSENT** | Only a 1-move countermove table keyed on `[side][prev_to_sq]` (`search.rs:893-896`) — 64-entry key is extremely coarse (standard key: prev piece×to-square, and 1/2-ply tables of full history values). |
| Capture history | **ABSENT** | — |
| Staged movegen / MovePicker | **ABSENT** | Every node: full `Vec<Move>` allocation (`movegen.rs:446-447`) + full sort. |
| Correction history | **ABSENT** | — |
| **Ordering cost bug** | — | `order_moves` (`search.rs:1053-1058`) calls `score_move` **inside the sort comparator** — 2·n·log(n) score computations per node, each possibly running full SEE. Standard: score once into an array (n SEE calls), or better, staged picking with lazy scoring. Pure speed loss, zero behavior change to fix. |

### C) Speed / NPS

| Item | Status | Evidence / notes |
|---|---|---|
| Board rep | **PRESENT** (bitboards) | `board.rs` — 12 piece bitboards. |
| Magic bitboards | **ABSENT** | `movegen.rs:111-144`: sliding attacks are **ray loops walking square by square** on every call. This sits under movegen, `attackers_to`, SEE, and check detection — the hottest paths in the engine. Magics (or even Kindergarten/rotating lookups) are a 5-20× speedup *of this function*. |
| Movegen | **PARTIAL** | Legal-only generation via make-and-test (`movegen.rs:262` comment, per pseudo-legal move: full board clone + check test). No captures-only generator for QS. `Vec` allocation per node. |
| Zobrist | **PARTIAL** | Keys exist (`board.rs:212-271`) but `zobrist_hash()` is **recomputed from scratch at every node** (`board.rs:282-283` "Compute Zobrist hash from scratch"; called `search.rs:1211`) — a 32-piece loop per node instead of an incremental XOR in make_move. |
| **NNUE accumulator: incremental?** | **NO — full rebuild every eval** | See §2. The single largest finding of this audit. |
| SIMD | **ABSENT** | See §2. All NNUE math is scalar loops over 512/1024 lanes. |
| TT prefetch | **ABSENT** | — |
| Copy-make | PRESENT (by design) | `movegen.rs:344-345` clones the Board per move. Fine at this size; the allocations (move Vecs) hurt more. |
| Measured NPS | — | **~106k (NNUE) / ~242k (PeSTO) single-thread.** Strong single-thread engines at similar feature level: 1-3M. We are 10-25× down on raw speed. |

### D) Eval / NNUE architecture

| Item | Status |
|---|---|
| Current net | (768→512)×2→1 SCReLU, QA=255/QB=64/SCALE=400, int16 weights, verified integer inference (`nnue.rs:20-47`). **Parameters: 768×512 + 512 + 1024 + 1 = 393,729 (~787KB).** |
| Output buckets (material/piece-count, 8×) | **ABSENT.** Cheapest arch win at our data scale (labels reused across buckets, ~8× output params only ≈ +8K params). Directly addresses Gate-M-style material calibration drift. |
| King input buckets | **ABSENT — data-gated.** Multiplies FT params by bucket count; at 42.8M positions we are 25-150× below the 1-6B-position corpora of engines using them. |
| Horizontal mirroring (king-half) | **ABSENT — data-gated** (halves effective input space, usually paired with king buckets). |
| Note | Tal/style eval terms apply **only on the PeSTO path** (`search.rs:813-830`); under NNUE the style lives in the net + search dynamics. Style gating of search changes is therefore *more* important now, not less. |

### E) Time management

| Item | Status | Evidence |
|---|---|---|
| Allocation | **PARTIAL — one fixed budget** | `main.rs:229-252`: `time/movestogo(30) + inc`, capped at 25% of clock, −50ms safety. That's the whole system. |
| Soft/hard limits | **ABSENT** | One deadline serves both "start another iteration?" (`search.rs:1600`) and mid-search abort. No soft limit ≈ wasted or overspent time every move. |
| Best-move stability scaling | **ABSENT** | — |
| Node-based TM (root node fractions) | **ABSENT** | — |
| Falling-eval scaling | **ABSENT** | — |

---

## 2. THE NPS QUESTION (answered specifically)

**Q: Is NNUE inference incremental or full-recompute?** **Full recompute, at every
single eval site.** The incremental primitives exist (`add_feature`/`remove_feature`,
`nnue.rs:119-136`) and are tested (`nnue.rs:479-493`) — but nothing in the search calls
them. Every evaluation does this instead:

```rust
// search.rs:1108-1110 (quiescence stand-pat; same pattern at :1192-1194,
// :1332-1334, :1438-1441)
let stand_pat = if let Some(net) = network {
    let acc = nnue::Accumulator::from_board(net, board);   // <-- FULL REBUILD
    net.evaluate(&acc, board.side_to_move)
```

`from_board` (`nnue.rs:139-167`) loops all ~32 pieces × `add_feature`, and each
`add_feature` is a 512-iteration scalar loop **twice** (both perspectives):

```rust
// nnue.rs:122-125
for i in 0..HIDDEN_SIZE {
    self.white[i] += network.ft_weights[w_idx][i] as i32;
    self.black[i] += network.ft_weights[b_idx][i] as i32;
}
```

That is ~32 × 2 × 512 ≈ **33,000 adds per eval** where an incremental engine does
~2-4 features × 2 × 512 ≈ **2-4k adds per move** (and zero on eval-less nodes). A move
touches at most 4 features (from, to, capture, promo/castle rook). The measured
106k-vs-242k NPS split says the NNUE path consumes ~56% of all search time; incremental
updates make that term nearly vanish. **Expected: ~2× NPS ≈ +1 ply ≈ +50-70 Elo, from
wiring up functions that already exist and already pass a round-trip test.**

**Q: Is there any SIMD?** **No.** The accumulator loops above and the output layer
(`nnue.rs:190-198`: 1024 scalar `i64` multiply-adds per eval) are plain scalar Rust.
The i16 weight layout is SIMD-ready as-is: AVX2 processes 16×i16 per instruction.
Options in ascending effort: (1) restructure loops so LLVM autovectorizes (fastest to
try: cast accumulator to i16, iterate fixed-size chunks — check `--emit=asm`);
(2) `std::arch` AVX2 intrinsics with a scalar fallback (what every Rust engine does);
(3) portable `std::simd` (nightly). Realistic 3-6× on the NNUE math that remains after
incrementalization. **Combined incremental+SIMD projection: ~400-600k nps, i.e. ~2-2.5
plies ≈ +100-170 Elo, before any search-feature work.**

Also in the hot path and worth naming: Zobrist recomputed from scratch per node
(`search.rs:1211`), ray-walk sliding attacks under everything (`movegen.rs:117-134`),
`score_move`-in-comparator sorting (`search.rs:1053-1058`), per-node `Vec` allocations,
and make-and-test legality filtering. Each is a pure-speed fix with a perft/bench
equivalence check — no search-behavior change, minimal SPRT risk.

---

## 3. PRIORITIZED ROADMAP

Elo figures are order-of-magnitude engine-dev folklore scaled to our ~2000 level
(gains are larger at lower rating), then **discounted for our documented 2-3×
optimism**. Effort: S < 1 day, M = 1-3 days, L = 1-2 weeks. Style column flags risk to
kz_sac/aggression floors (every gauntlet keeps the style gate regardless).

### Tier 1 — cheap, high-Elo, no new data (search + integration)

| # | Change | Est. Elo | Effort | Risk | Style risk |
|---|---|---|---|---|---|
| 1 | **Incremental NNUE accumulator** (thread acc stack through make_move path) | +50-90 (speed) | M | Low — primitives exist + tested; verify vs `from_board` on 10k random positions (we have that harness pattern) | None (identical evals) |
| 2 | **Fix move-ordering cost** (score once per node, not per comparison) | +10-25 (speed) | S | Trivial | None |
| 3 | **Log-formula LMR** + re-search on fail-high above reduced depth | +50-90 | S-M | Low; biggest single search gap | **Yes — flag.** Deeper reductions of "quiet junk" can prune speculative attacking quiets. Gauntlet must check kz_sac. |
| 4 | **RFP** (eval − 70·depth ≥ beta → return, depth ≤ ~7, not in PV/check) | +25-50 | S | Low | Mild — prunes when *winning*, rarely style-relevant |
| 5 | **QS: TT probe/store + delta pruning + captures-only generation** | +20-40 | M | Medium (QS TT bugs are subtle) | None |
| 6 | **NMP dynamic R** (3 + depth/3, + eval-gap term; proper zugzwang guard) | +15-30 | S | Low | None |
| 7 | **Aspiration gradual widening** (±50 → ±115 → ±270 → INF) | +5-15 | S | Trivial | None |
| 8 | **Continuation history** (1-ply CMH keyed piece×to, then 2-ply FMH) + use in LMR/ordering | +30-60 | M | Medium | Mild |
| 9 | **SEE pruning in main search** (skip bad captures depth≤6 at margin, quiets via history) | +20-40 | S-M | Low | **Yes — flag** (prunes sacrifice-shaped captures; the style gate exists precisely for this) |
| 10 | **Time management: soft/hard split + best-move-stability scaling** | +20-40 (real games only) | S-M | Low | None |
| 11 | **UCI Hash option + TT: trust older-gen entries, return entry score, store static eval** | +10-25 | S-M | Low | None |
| 12 | LMP + improving heuristic (re-opened — see §4) | +15-35 | S-M | Medium | **Yes — flag** |
| 13 | IIR (replace dormant IID) | +5-15 | S | Trivial | None |

Tier 1 realistic sum after overlap discounting (pruning gains overlap with each other
and with depth): **+250-400 Elo.**

### Tier 2 — speed/NPS infrastructure

| # | Change | Est. Elo | Effort | Risk |
|---|---|---|---|---|
| 14 | **SIMD NNUE** (i16 accumulator + AVX2 or autovectorized loops; also SIMD the SCReLU output layer) | +40-80 | M-L | Medium — needs exact-match harness vs scalar (10k-position equivalence, the SCReLU-512 verification pattern) |
| 15 | **Magic bitboards** (or Kindergarten) for sliders | +30-60 | M | Low — perft is a complete correctness oracle |
| 16 | **Incremental Zobrist** in make_move | +10-20 | S | Low (perft-hash check) |
| 17 | Staged MovePicker (TT → good captures → killers → quiets by history), stack-allocated move list | +20-40 | L | Medium |
| 18 | TT prefetch after make_move | +3-8 | S | Trivial |
| 19 | Add `bench` + `info nodes nps` output (measurement hygiene; free) | 0 | S | — |

Tier 2 realistic sum: **+100-180 Elo** (mostly via the ~2 plies the speed buys).

### Tier 3 — data-gated NNUE architecture (needs corpus growth first)

| # | Change | Est. Elo | Gate |
|---|---|---|---|
| 20 | **Output buckets (8, by piece count)** | +20-50 | Worth testing at 42.8M NOW (params +8K only) — the one Tier-3 item not data-blocked; rho-gate then SPRT |
| 21 | Corpus scale-up (42.8M → 150-300M via the proven v2 pipeline; gen ~185/s + relabel ~200/s ≈ 2-3 weeks per 100M) | net quality: +30-80 | Disk + weeks of compute; the pipeline is armored and proven |
| 22 | King buckets + horizontal mirroring | +50-120 | **Blocked** until ≥several hundred M positions; at 42.8M would likely *lose* (Session-1 lesson: architecture ahead of data ranks worse) |
| 23 | Deeper/bigger nets (768→1024, L2 layers) | ? | Same data gate + inference-speed tradeoff (bigger net halves NPS — must SPRT net+speed jointly) |

---

## 4. THE ONE-VARIABLE PLAN (implementation order)

Dependencies respected; each lands alone, no-op-proofed where applicable, then gauntlet
per our rules (≥100 games verdicts, style floor checked on every search change).
Speed-only changes (marked ⚡) are verified by equivalence (identical best-move/score on
a fixed position suite + perft) and can batch into one SPRT since behavior is untouched.

1. ⚡ `bench` + nps output (#19) — instrument before optimizing.
2. ⚡ Incremental accumulator (#1) — biggest single win, zero behavior change.
3. ⚡ Ordering-cost fix (#2), incremental Zobrist (#16). One equivalence-SPRT for 1-3.
4. Log-LMR (#3) — **style-gated gauntlet**.
5. RFP (#4).
6. NMP dynamic R (#6).
7. QS overhaul (#5) — TT in QS before delta pruning (delta needs the TT-corrected evals).
8. Aspiration widening (#7) + TT trust/Hash option (#11).
9. Continuation history (#8) — after ordering infrastructure settles; **then** history-based LMR adjustment as its own step.
10. SEE pruning (#9) — **style-gated**.
11. **Re-open the parked trio** — the PeSTO-era verdicts don't transfer: IID was neutral and LMP catastrophic *against a hand-crafted eval at ~106k nps with 1-ply LMR*; with NNUE eval accuracy, log-LMR, and CMH in place, LMP+improving (#12) and IIR (#13) are standard-stack members. Re-test each alone. (dep-NMP folds into #6.)
12. Time management (#10) — last among Tier 1 because it only shows in real-clock gauntlets (our Feral config), not fixed-node tests.
13. Tier 2: SIMD (#14) → magics (#15) → MovePicker (#17) → prefetch (#18), each equivalence-checked.
14. Tier 3: output buckets (#20) immediately after Tier 1 stabilizes (it's a training run, parallel track); corpus scale-up (#21) as the background campaign when disk allows; king buckets/mirroring (#22) only after.

Settled work NOT re-opened: G2 Lazy SMP (shipped), eval-side beauty terms
(DYNAMIC/COMP — closed with sign-off), G9 ordering bonus (closed), WDL (one retry spent
per Phase D rules — governed separately).

---

## 5. HONEST CEILING

Current: T1 ~1988 / T4 ~2000-class on our internal SF-UCI_Elo yardstick, ~106k nps,
~394k-param net trained on 42.8M positions.

**(a) Search + speed on the current net:** Tier 1 (+250-400) and Tier 2 (+100-180)
overlap — speed's plies and pruning's plies buy some of the same depth. Discounted
honestly (our 2-3× optimism history applied): **+300-450 Elo → ~2300-2450.** The
limiting factor becomes the net's judgment at depths its labels never saw (d12 labels,
searches reaching d18+).

**(b) + bigger corpus and architecture:** output buckets now, 150-300M corpus over 1-2
months of background compute, then king buckets/mirroring, retrained at 512-wide:
realistically **+100-200 over (a) → ~2450-2650.** A ~2800 engine on this hardware is
not credible without both a much larger data campaign (billions of positions — months)
and a mature SIMD/incremental infrastructure running near 1M+ nps; treat 2800 as
aspirational, not plannable.

The encouraging inversion: historically our estimates ran hot on *eval* experiments.
Search-feature Elo at the 2000 level is the best-documented territory in engine
development — these are the same features every engine that climbed 2000→2500 used, in
roughly this order. The risk isn't direction; it's per-item magnitude and our style
constraint, which is exactly what the gauntlet + style floor already measure.

---

*Audit complete. No code, nets, or configs were modified; nothing was committed. Live
nets verified untouched: `pyro.nnue` (SCReLU-512 champion) md5
`9f01010bfe8b41193f77a9fad88abd56` at both locations; PeSTO-era backup
`23bfcd331411b8b9c6a05191d42caef5` intact.*
