/*
Pyro NNUE trainer — CANDIDATE B of the July 12, 2026 capacity ladder.

Identical to pyro.rs (the expE config retrained on GPU) except ONE variable:
  activation CReLU -> SCReLU (clip(x,0,1)^2).

Everything else matches expE: (768 -> 256)x2 -> 1, eval-only (WDL=0),
STOCK loss convention, SB30, batch 16384, cosine 1e-3 -> 1e-5.

NOTE: engine/src/nnue.rs implements CReLU inference — a SCReLU net CANNOT
be evaluated by the shipping engine (inference must square the clipped
accumulator, and the quantised output needs a /QA renormalisation:
crelu^2 in [0,1] -> quantised (clip(acc,0,QA))^2 in [0,QA^2], so
eval = (sum + bias*QA) * SCALE / (QA*QA*QB) — see bullet examples/simple.rs).
Gate checks run on raw.bin (float) with SCReLU applied in the gate script.

Data: SF18 re-eval at depth 12 — C:/torch_data/selfplay_v2_sf18.data
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

const HIDDEN_SIZE: usize = 512;
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
        // (768 -> 256)x2 -> 1 with SCReLU
        .build(|builder, stm_inputs, ntm_inputs| {
            let l0 = builder.new_affine("l0", 768, HIDDEN_SIZE);
            let l1 = builder.new_affine("l1", 2 * HIDDEN_SIZE, 1);

            let stm_hidden = l0.forward(stm_inputs).screlu();
            let ntm_hidden = l0.forward(ntm_inputs).screlu();
            let hidden_layer = stm_hidden.concat(ntm_hidden);
            l1.forward(hidden_layer)
        });

    let schedule = TrainingSchedule {
        net_id: "pyro-gpu-screlu".to_string(),
        eval_scale: SCALE as f32,
        steps: TrainingSteps {
            batch_size: 16_384,
            batches_per_superbatch: 1221,
            start_superbatch: 1,
            end_superbatch: 30,
        },
        wdl_scheduler: wdl::ConstantWDL { value: 0.0 },
        lr_scheduler: lr::CosineDecayLR { initial_lr: 1e-3, final_lr: 1e-5, final_superbatch: 30 },
        save_rate: 10,
    };

    let settings = LocalSettings {
        threads: 4,
        test_set: None,
        output_directory: "checkpoints/pyro-gpu-screlu",
        batch_queue_size: 64,
    };

    let data_loader = loader::DirectSequentialDataLoader::new(&[
        "C:/torch_data/selfplay_v2_sf18_wdlclean.data",
    ]);

    trainer.run(&schedule, &settings, &data_loader);
}
