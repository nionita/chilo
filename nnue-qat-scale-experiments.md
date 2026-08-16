# NNUE QAT Scale Experiments

This document records the generation-4 NNUE architecture and quantization-scale
experiments. It is an operator log: record completed runs and decisions here so
validation, export, benchmark, and SPRT results remain connected.

## Scope And Status

The current runtime format is `byte_dense_shift_v1`, trained with
`fake-byte-shift` QAT. All scales are positive powers of two, so runtime uses
shifts rather than general divisions.

Generation-4 data contains 188,079,420 train samples and 10,000,000 validation
samples. It was generated from generation-3 self-play at search depth 6. Losses
are comparable between generation-4 runs using this same prepared dataset and
target, but are not strength results. Playing strength requires benchmark and
SPRT evidence.

The `128 -> 8` architecture run is in progress. Scale screening starts only
after choosing the architecture to tune.

## Scale Semantics

The three factors affect different stored tensors. Larger scales provide finer
quantization steps but reduce the representable floating-point range before the
fixed integer type clips.

| Scale | Stored representation | Float step | Float weight limit |
|---|---|---:|---:|
| `input_scale = S_i` | `int16`, `round(w * S_i)` | `1 / S_i` | `32767 / S_i` |
| `hidden_scale = S_h` | `int8`, `round(w * 2S_h)` | `1 / (2S_h)` | `127 / (2S_h)` |
| `output_scale = S_o` | `int8`, `round(w * 2S_o)` | `1 / (2S_o)` | `127 / (2S_o)` |

The established QAT setting is `32 / 4 / 8`:

- input step `1/32`, range about `+/-1024`
- second-layer weight step `1/8`, range `+/-15.875`
- output-weight step `1/16`, range `+/-7.9375`
- final score rounding step `1/8`

The scales do not materially alter inference speed: they are shift counts and
do not change layer dimensions or the number of byte dot products. They do
change the learned quantized model, so a QAT checkpoint must be trained using
the same scales that will be exported.

## Completed Architecture Runs

| Run | Layers | Scales | Training | Best validation loss | Status |
|---|---|---|---|---:|---|
| `g4t1-64x8` | `64 -> 8` | `32 / 4 / 8` | 24 epochs, cosine `1e-2 -> 1e-4`, batch 4096, 3 workers | `0.121880` | Exported; architecture candidate |
| `g4t2-32x16` | `32 -> 16` | `32 / 4 / 8` | 24 epochs, cosine `1e-2 -> 1e-4`, batch 4096, 4 workers | `0.122947` | Exported; lower priority due to worse loss |
| `g4t3-128x8` | `128 -> 8` | `32 / 4 / 8` | In progress | pending | Await training, export, and benchmark |

The first two runs used the same generation-4 dataset and target. Their loss
gap supports the conclusion that accumulator capacity is more valuable here
than widening the second dense layer at equal dense-layer weight count. Their
training did not use TensorBoard, so no QAT saturation diagnostics were saved.

## QAT Scale Screening Protocol

Run a short QAT screen before committing a candidate scale setting to a normal
24-epoch training run. The short screen is for rejecting unsuitable ranges and
for selecting full-run candidates; it is not a playing-strength test.

### Fixed Conditions

For one scale screen, keep the following fixed:

- chosen architecture and generation-4 dataset
- `fake-byte-shift` quantization mode
- batch size, device, worker count, shuffle-buffer size, initializer, and
  result/score target settings
- seed where practical, to reduce avoidable ordering and initialization noise

Use four epochs at constant `1e-2` learning rate. This approximates the early
part of the normal 24-epoch cosine run while keeping the screen short. Enable
TensorBoard and disable histograms to retain scalars without large event files:

```text
--epochs 4 --lr-schedule constant --learning-rate 1e-2
--tensorboard-dir <run-specific-tb-directory> --no-tb-hist
```

The baseline screen is `32 / 4 / 8`. It must be run with the same screening
conditions as the variants. The operator has completed this baseline; record
its exact run path and metrics below when available.

### Initial Candidate Order

Change one scale at a time. Start with the `int8` dense layers, where range
limits are most likely to matter:

| Purpose | Input | Hidden | Output |
|---|---:|---:|---:|
| Baseline | 32 | 4 | 8 |
| More hidden range, less precision | 32 | 2 | 8 |
| More hidden precision, less range | 32 | 8 | 8 |
| More output range, less precision | 32 | 4 | 4 |
| More output precision, less range | 32 | 4 | 16 |

Only after selecting plausible dense-layer scales, screen input scales `16 / 4 / 8`
and `64 / 4 / 8`. The input layer uses `int16`, so it has substantially more
headroom than the dense/output layers.

### TensorBoard Signals

Inspect the following scalars against the baseline:

- `loss/val`: QAT validation loss for the actual fake-byte-shift forward path
- `qat/hidden2_weight_clip_frac` and `qat/output_weight_clip_frac`: global
  fractions of quantized dense/output weights pinned at the `int8` boundary
- `qat/accumulator_byte_val_max_frac` and `qat/hidden2_byte_val_max_frac`:
  sampled byte-activation saturation
- `activation/accumulator_val_clip_frac` and
  `activation/hidden2_val_clip_frac`: full-validation activation summaries

The dense/output weight clipping fractions are global. The QAT byte activation
statistics come from the first validation batch, so compare trends rather than
treating one value as exact. The ordinary validation activation summaries are
aggregated over the full validation set.

The current trainer does not log an input `int16` weight clipping fraction. An
input-scale decision therefore relies on loss and activation behavior unless
that diagnostic is added later.

### Screening Decisions

Reject a scale setting without a full run when it has both a persistent
validation-loss disadvantage in the later screening epochs and a plausible QAT
cause, such as materially higher weight clipping or activation saturation.

Keep a setting for full training when it has comparable or better short-run
validation loss without concerning diagnostics. Do not reject a candidate only
because one metric is imperfect: QAT may deliberately use some clipping, and
a small early-loss difference can change in a full cosine run.

Short screening runs do not need export. Export only normal 24-epoch finalists,
then record the runtime `.bin` metadata and QAT/export diagnostics before engine
benchmarking and SPRT.

## Scale Screen Results

| Run | Architecture | Scales | TensorBoard path | Epoch-4 validation loss | Diagnostics summary | Decision |
|---|---|---|---|---:|---|---|
| Baseline | pending architecture | `32 / 4 / 8` | pending | pending | pending | pending |
| Variant | pending | pending | pending | pending | pending | pending |

## Final Decision Log

Record one entry for each architecture or scale setting promoted beyond short
screening:

| Candidate | Full-run validation loss | Export diagnostics | Eval/search benchmark | SPRT result | Decision and rationale |
|---|---:|---|---|---|---|
| pending | pending | pending | pending | pending | pending |
