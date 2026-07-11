/*
Pyro NNUE trainer — GPU port of the expE configuration (July 2026).

Ported from the pinned-bullet (feab6443) CPU-backend version to bullet main
(cebc78a0, cudarc removed, direct CUDA linking). Faithful to expE except:
  - `.use_devices(vec![()])` removed — the method no longer exists; device
    selection is automatic (build with `--features cuda`).
  - net_id/output_directory renamed pyro-expE → pyro-gpu so no run can ever
    overwrite the checkpoints/pyro-expE record (the only trained-net record).
  - imports follow main's example style.

Everything below matches expE (see backend/scripts/pyro.rs.expE_backup):
(768 -> 256)x2 -> 1, CReLU, eval-only (WDL=0), STOCK loss convention.

  Training: output.sigmoid()
  Inference: eval = (accum + bias) * SCALE / (QA*QB)  — engine/src/nnue.rs
SCALE = 400 in BOTH this file and engine/src/nnue.rs — they MUST agree.

Data: SF18 re-eval at depth 12 — C:/torch_data/selfplay_sf18_d12.data
*/
use bullet_lib::{
    game::inputs::Chess768,
    nn::optimiser::AdamW,
    trainer::{
        save::SavedFormat,
        schedule::{TrainingSchedule, TrainingSteps, lr, wdl},
        settings::LocalSettings,
    },
    value::{ValueTrainerBuilder, loader},
};

const HIDDEN_SIZE: usize = 256;
const SCALE: i32 = 400;
const QA: i16 = 255;
const QB: i16 = 64;

fn main() {
    let mut trainer = ValueTrainerBuilder::default()
        .dual_perspective()
        .optimiser(AdamW)
        .inputs(Chess768)
        // Quantisation constants match engine/src/nnue.rs exactly
        .save_format(&[
            SavedFormat::id("l0w").round().quantise::<i16>(QA),
            SavedFormat::id("l0b").round().quantise::<i16>(QA),
            SavedFormat::id("l1w").round().quantise::<i16>(QB),
            SavedFormat::id("l1b").round().quantise::<i16>(QA * QB),
        ])
        // Stock Bullet loss: output.sigmoid() keeps l1w in ±0.045 regime.
        // Inference partner: eval = (accum + bias) * SCALE / (QA*QB) in nnue.rs.
        .loss_fn(|output, target| output.sigmoid().squared_error(target))
        // (768 -> 256)x2 -> 1 with CReLU
        .build(|builder, stm_inputs, ntm_inputs| {
            let l0 = builder.new_affine("l0", 768, HIDDEN_SIZE);
            let l1 = builder.new_affine("l1", 2 * HIDDEN_SIZE, 1);

            let stm_hidden = l0.forward(stm_inputs).crelu();
            let ntm_hidden = l0.forward(ntm_inputs).crelu();
            let hidden_layer = stm_hidden.concat(ntm_hidden);
            l1.forward(hidden_layer)
        });

    // 30 superbatches ≈ 30 epochs over 20M positions.
    // batches_per_superbatch = ceil(20M / 16384) ≈ 1221 → one pass per superbatch.
    let schedule = TrainingSchedule {
        net_id: "pyro-gpu".to_string(),
        eval_scale: SCALE as f32,
        steps: TrainingSteps {
            batch_size: 16_384,
            batches_per_superbatch: 1221,
            start_superbatch: 1,
            end_superbatch: 30,
        },
        wdl_scheduler: wdl::ConstantWDL { value: 0.0 },
        // Cosine decay 1e-3 → 1e-5 over full training run
        lr_scheduler: lr::CosineDecayLR { initial_lr: 1e-3, final_lr: 1e-5, final_superbatch: 30 },
        save_rate: 10,
    };

    let settings = LocalSettings {
        threads: 4,
        test_set: None,
        output_directory: "checkpoints/pyro-gpu",
        batch_queue_size: 64,
    };

    let data_loader = loader::DirectSequentialDataLoader::new(&[
        "C:/torch_data/selfplay_sf18_d12.data",
    ]);

    trainer.run(&schedule, &settings, &data_loader);
}
