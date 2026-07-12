/*
Pyro NNUE trainer — CANDIDATE D4 of the July 12, 2026 WDL ladder (session 2a): CReLU CONTROL at WDL 0.1 — completes the activation x WDL 2x2 vs C0/B/D1.

Identical to pyro.rs (the expE config retrained on GPU) except ONE variable
vs candidate 0: WDL blend 0.1 (CReLU retained). Equivalently: D1 (wdl01)
with SCReLU -> CReLU. Isolates whether the WDL-0.1 penalty is
activation-independent.

Everything else matches expE: (768 -> 256)x2 -> 1, CReLU,
STOCK loss convention, SB30, batch 16384, cosine 1e-3 -> 1e-5.
Gate checks run on raw.bin (float) with CReLU applied in the gate script.

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
        .save_format(&[
            SavedFormat::id("l0w").round().quantise::<i16>(QA),
            SavedFormat::id("l0b").round().quantise::<i16>(QA),
            SavedFormat::id("l1w").round().quantise::<i16>(QB),
            SavedFormat::id("l1b").round().quantise::<i16>(QA * QB),
        ])
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

    let schedule = TrainingSchedule {
        net_id: "pyro-gpu-wdl01-crelu".to_string(),
        eval_scale: SCALE as f32,
        steps: TrainingSteps {
            batch_size: 16_384,
            batches_per_superbatch: 1221,
            start_superbatch: 1,
            end_superbatch: 30,
        },
        wdl_scheduler: wdl::ConstantWDL { value: 0.1 },
        lr_scheduler: lr::CosineDecayLR { initial_lr: 1e-3, final_lr: 1e-5, final_superbatch: 30 },
        save_rate: 10,
    };

    let settings = LocalSettings {
        threads: 4,
        test_set: None,
        output_directory: "checkpoints/pyro-gpu-wdl01-crelu",
        batch_queue_size: 64,
    };

    let data_loader = loader::DirectSequentialDataLoader::new(&[
        "C:/torch_data/selfplay_sf18_d12.data",
    ]);

    trainer.run(&schedule, &settings, &data_loader);
}
