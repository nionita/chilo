# NNUE v3 Inference Optimization Notes

This document records the current NNUE v3 inference findings and a staged
optimization plan. The goal is to avoid repeating the architecture analysis
when implementing the changes over several steps.

The current network is intentionally simple:

```text
sparse relative piece-square features
    -> shared feature transformer
    -> white and black accumulators
    -> active/passive concatenation
    -> ClippedReLU
    -> dense hidden layer
    -> ClippedReLU
    -> output
```

The default dimensions at the time of writing are:

```text
13 * 64 sparse inputs -> 64 accumulator neurons per perspective
2 * 64 dense inputs   -> 32 hidden neurons
32 dense inputs       -> 1 output
```

The input feature-transformer parameters are already shared between the white
and black perspectives. The perspective-specific difference comes from
friendly/enemy piece remapping and square normalization. At evaluation time,
the side-to-move accumulator is placed in the first half of the dense input and
the opponent accumulator in the second half. The dense hidden layer therefore
has independent parameters for active and passive treatment.

Implementation status: version `0.7.3` implements Stage 2's byte-dense export
and inference format. Sparse feature-transformer weights and accumulator bias
remain `int16_t`, accumulator storage remains `int32_t`, dense/output weights
are now `int8_t`, activations are requantized to `0..127` using rounded shifts,
runtime binaries use `CHNNUEB5`, and export manifests use
`chilo.nnue_export.v8`. Version `0.7.2` was the first byte-dense implementation
and still used real divisions for activation requantization.

Relevant Chilo files:

- `eval.cpp`: runtime network format and integer inference
- `engine.h`: accumulator representation
- `search.cpp`: per-ply accumulator frames and evaluation calls
- `scripts/export_nnue.py`: quantization and exported format
- `scripts/nnue_common.py`: Python integer parity implementation
- `scripts/nnue_contract.json`: feature and network contract
- `scripts/nnue_torch.py`: training model

## Important Comparison Caveat

Stockfish's high NPS is not explained by NNUE inference alone. It also has a
much more optimized search, move generator, memory layout, compiler setup, and
node-counting convention. Direct NPS comparisons between Chilo and Stockfish
are therefore not useful for estimating the cost of one NNUE layer.

The useful measurements for Chilo are:

1. An evaluation microbenchmark with a fixed set of positions.
2. Fixed-depth wall time when node counts and search behavior are identical.
3. A profiler showing the relative cost of accumulator maintenance and dense
   inference.
4. Strength tests after any quantization or architecture change.

HalfKP or a similar large sparse feature set does not make every incremental
evaluation proportional to the total number of possible input features. Only
active feature rows are added or removed. Larger feature sets mainly increase
network size, cache pressure, training difficulty, and refresh cost when a
feature dependency such as the king square changes.

## Previous Chilo Integer Pipeline

This was the pre-`0.7.2` pipeline kept here as background for why byte-dense
inference was introduced.

The old exported pipeline used:

| Value | Old type |
| --- | --- |
| Feature-transformer weights | `int16_t` |
| Feature-transformer bias | `int16_t` |
| Accumulator values | `int32_t` |
| Dense hidden weights | `int16_t` |
| Dense hidden bias | `int32_t` |
| Dense hidden intermediate | `int64_t` |
| Output weights | `int16_t` |
| Output bias and score | `int32_t` / `int64_t` |

The generated fallback manifest used three scales:

```text
input_scale  = 64
hidden_scale = 32
output_scale = 32
clip_max     = 255
```

The scales are carried through the entire network and divided out only at the
end:

```text
final_divisor = input_scale * hidden_scale * output_scale
```

This is simple and preserves relatively fine precision, but it prevents the
dense layers from using the byte-oriented SIMD operations that make NNUE
inference fast.

## Current Hot-Path Findings

### Sparse input layout is already appropriate

The input weights are stored as:

```text
input_weights[relative_piece][normalized_square][hidden]
```

Each active feature selects one contiguous row of `hidden` weights. This is the
right layout for sparse accumulator updates and should be preserved for the
simple feature set and later for HalfKP.

### Dense inference repeats ClippedReLU work

`scoreFromLanes()` loops over every hidden-layer output neuron and calls
`dotClippedLane()` once for the active lane and once for the passive lane.
`dotClippedLane()` clamps every accumulator element before multiplying it.

For a `64x2 -> 32` dense layer, each of the 128 accumulator values is therefore
clamped 32 times. The activation is independent of the output neuron, so it
should be computed once per evaluation.

### Current AVX2 dense dot product leaves throughput unused

The current AVX2 implementation:

1. Loads eight `int32_t` accumulator values.
2. Loads eight `int16_t` weights.
3. Expands the weights to `int32_t`.
4. Multiplies eight lanes.
5. Stores the products to a temporary array.
6. Sums the temporary array with a scalar loop.

This is better than fully scalar inference, but it uses only eight products per
256-bit vector and pays a memory round trip plus scalar reduction for every
vector. The new dense layer performs `2 * 64 * 32 = 4096` multiply-adds per
evaluation, so this matters.

### Accumulator updates and copies are wider than necessary

The accumulator stores `int32_t` values even though feature-transformer weights
are `int16_t`. The AVX2 update path must expand eight weights at a time before
adding or subtracting them.

Each `64x2` child accumulator frame contains 128 `int32_t` values, or 512
bytes, before vector metadata. `prepareChildSearchNnue()` copies this frame and
then applies the move delta. An `int16_t` accumulator would halve copy traffic
and double the number of values updated per AVX2 instruction.

This cannot be changed safely without proving that unclipped accumulator values
cannot overflow. Saturating additions are not valid for incremental
accumulators because adding and later subtracting a feature must restore the
original exact value.

## Stockfish Techniques Relevant To Chilo

The Stockfish NNUE documentation describes the general low-precision pipeline:

- feature-transformer weights and accumulators use wider integers
- ClippedReLU converts accumulator values to byte activations
- dense affine weights use signed bytes
- dense affine outputs and biases use `int32_t`
- weight scales are normally powers of two so divisions become shifts

Current Stockfish master is no longer a plain HalfKP network. At the time of
this analysis it declares `HalfKAv2_hm`, `FullThreats`, an `L1` size of 1024,
and small later layers. Its exact architecture is outside the scope of Chilo's
simple ClippedReLU network, but its integer types, packed matrix layouts, and
SIMD affine-transform techniques remain directly relevant.

The most useful Stockfish implementation details are:

1. `FeatureTransformer` accumulates with `int16_t` weights and biases, then
   produces `uint8_t` transformed features.
2. Dense `AffineTransform` layers take `uint8_t` inputs, use `int8_t` weights,
   and accumulate into `int32_t` outputs.
3. Dense weights are stored in a scrambled layout for SIMD processing in
   chunks of four inputs.
4. AVX2 dot products use `_mm256_maddubs_epi16()` followed by
   `_mm256_madd_epi16()` and `_mm256_add_epi32()`.
5. Output dimensions are processed in parallel in SIMD registers, avoiding a
   horizontal reduction for every hidden neuron.
6. Dimensions and buffers are padded and cache-line aligned.

References:

- NNUE description and optimization examples:
  <https://github.com/official-stockfish/nnue-pytorch/blob/master/docs/nnue.md>
- Current Stockfish dense affine transform:
  <https://github.com/official-stockfish/Stockfish/blob/master/src/nnue/layers/affine_transform.h>
- Current Stockfish feature transformer:
  <https://github.com/official-stockfish/Stockfish/blob/master/src/nnue/nnue_feature_transformer.h>
- Current Stockfish architecture:
  <https://github.com/official-stockfish/Stockfish/blob/master/src/nnue/nnue_architecture.h>
- Current Stockfish SIMD helpers:
  <https://github.com/official-stockfish/Stockfish/blob/master/src/nnue/simd.h>

## Proposed Optimization Stages

The stages below are ordered so that each can be measured independently. Do not
combine all changes into one implementation. Quantization and layout changes
make failures harder to diagnose, and their strength effects need separate
testing.

### Stage 0: Add repeatable measurements

Before changing inference, add an evaluation microbenchmark that:

- evaluates a stable corpus of representative positions
- supports rebuilt and incremental-accumulator evaluation
- reports evaluations per second and a checksum
- can compare generic and AVX2 binaries
- uses a runtime trained network as well as the built-in fallback network

Also keep a fixed-depth search workload with recorded node counts, PVs, and
wall times. `performance.md` already explains why wall time with identical node
counts is more reliable than NPS alone for small speed comparisons.

### Stage 1: Optimize the current format without breaking compatibility

This stage should preserve the existing network file format, integer results,
and Python parity behavior.

1. Clamp the active and passive accumulators once into a temporary dense input
   buffer before looping over hidden neurons.
2. Replace the AVX2 product temporary array and scalar sum with vector
   accumulators and an in-register horizontal reduction.
3. Evaluate one contiguous `2 * hidden_size` dense input rather than calling a
   lane dot-product helper twice.
4. Consider cache-line alignment for accumulator and temporary buffers.
5. Preserve a simple scalar implementation for the generic build.

Expected result: a contained speedup with low risk and no retraining. This is
the first implementation step because the current repeated clipping is clearly
unnecessary.

### Stage 2: Introduce byte activations and byte dense weights

This is the most important dense-inference optimization and requires a new
network format and quantization contract.

Target inference types:

| Value | Target type |
| --- | --- |
| Feature-transformer weights | `int16_t` |
| Feature-transformer bias | `int16_t` initially |
| Accumulator values | `int32_t` initially |
| Clipped accumulator output | `uint8_t` |
| Dense hidden weights | `int8_t` |
| Dense hidden bias/output | `int32_t` |
| Clipped hidden output | `uint8_t` |
| Output weights | `int8_t` |
| Output bias/output | `int32_t` |

The important design problem is not only changing C++ types. The training and
export pipeline must define where scales are removed between layers.

The current pipeline carries all three scales until the final division. A byte
pipeline instead needs explicit intermediate requantization, normally with
power-of-two divisors or shifts:

```text
int16/int32 accumulator
    -> clamp and requantize
    -> uint8 activation
    -> int8 dense weights, int32 accumulation
    -> shift, clamp, and requantize
    -> uint8 activation
    -> int8 output weights, int32 accumulation
    -> final output scaling
```

The current `clip_max = 255` and `input_scale = 64` cannot simply be packed
without deciding how much precision to discard. Packing
`clamp(accumulator / input_scale, 0, 255)` would quantize activations in steps
of one float unit, much more coarsely than the current dense computation.

The likely clean solution is to train in a normalized activation domain and
make the accumulator scale correspond directly to the byte activation range,
similar to the common NNUE convention where a float ClippedReLU range maps to
`0..127`. Fake-quantization or quantization-aware validation should be added
before relying on this format for strength.

#### AVX2 correctness constraint

The AVX2 byte dot-product sequence is:

```cpp
product16 = _mm256_maddubs_epi16(unsigned_inputs, signed_weights);
product32 = _mm256_madd_epi16(product16, ones);
sum32 = _mm256_add_epi32(sum32, product32);
```

`_mm256_maddubs_epi16()` uses saturating signed 16-bit pair sums. This is safe
only if each adjacent pair of byte products cannot exceed the signed 16-bit
range. With inputs and weights limited to `0..127` and `-127..127`, the maximum
positive pair sum is `2 * 127 * 127 = 32258`, which fits. Allowing unsigned
activations up to 255 can overflow this intermediate and silently produce
incorrect results unless the implementation uses a different strategy.

For that reason, a `0..127` activation range is the simpler AVX2 contract.

### Stage 3: Pack the dense weight matrices for AVX2

The current dense matrix is row-major:

```text
hidden2_weights[output_neuron][input_neuron]
```

That layout is convenient for scalar row dot products, but it requires a
horizontal reduction for every output neuron.

For AVX2 output-parallel evaluation, store weights in four-input chunks:

```text
packed_weights[input_chunk][output_neuron][4]
```

For each four-byte input chunk:

1. Load the four input bytes and broadcast them across an AVX2 register.
2. Load packed weights for a group of output neurons.
3. Apply the byte dot-product sequence.
4. Accumulate directly into `int32_t` vectors holding output neurons.

With 32 hidden outputs, four AVX2 registers can hold all output accumulators.
The hidden layer can then be produced without one horizontal reduction per
neuron.

Implementation choices:

- Keep a canonical row-major representation in the file and repack at load
  time. This keeps exported files architecture-independent and makes parity
  inspection easier.
- Or export the packed representation as part of the network format. This
  reduces startup work but makes the format more closely tied to one kernel.

The first option is preferable initially. Runtime network loading is rare, and
the packed representation can be derived once.

The generic implementation can continue using canonical row-major weights. The
AVX2 runtime structure may hold an additional packed copy.

### Stage 4: Convert accumulators to `int16_t`

After dense inference is efficient, accumulator update and frame-copy cost may
again dominate. Converting accumulator storage from `int32_t` to `int16_t`
would:

- update 16 values per AVX2 instruction instead of 8
- remove `int16_t` to `int32_t` weight expansion
- halve per-ply accumulator frame copy traffic
- improve cache density

This stage requires evidence that every unclipped accumulator remains within
`int16_t` range for all reachable positions and trained weights.

Required safeguards:

1. Export-time checks for conservative worst-case bounds where possible.
2. Training and validation statistics for accumulator pre-activation minima and
   maxima.
3. Weight or bias constraints if observed ranges approach the limit.
4. A validate-mode `int32_t` reference accumulator cross-check.
5. Tests covering repeated incremental add/subtract restoration.
6. No saturating accumulator arithmetic.

The current clipped maximum `255 * 64 = 16320` fits in `int16_t`, but clipping
occurs only during evaluation. Unclipped accumulator values may be outside that
range, so the clipped maximum alone is not proof of safety.

### Stage 5: Consider lazy accumulator updates

Chilo currently copies the parent accumulator frame and applies the move delta
before entering a searched child. Some children may return through TT or other
early exits before evaluation, so that work can be wasted.

A lazy accumulator stack would store pending move deltas and materialize the
accumulator only when evaluation needs it. This is a larger search/evaluator
integration change and should be considered only after profiling the earlier
stages.

This becomes more important for HalfKP because king moves can invalidate a
perspective accumulator and require a refresh. Stockfish uses accumulator
stacks and caches to reduce refresh cost. Chilo should not copy that machinery
blindly; the design should match Chilo's search state and feature contract.

## Additional Lower-Priority Measures

These may help, but should not distract from the byte dense pipeline:

- Pad hidden dimensions to SIMD widths and eliminate tail loops.
- Use cache-line-aligned buffers and weights.
- Specialize common built-in dimensions while retaining a generic runtime
  fallback for arbitrary network sizes.
- Ensure power-of-two quantization scales so divisions become shifts.
- Evaluate the final output layer with one SIMD byte dot product.
- Avoid unnecessary runtime-net lookups and repeated scale calculations in hot
  functions.
- Measure whether dynamic `std::vector` accumulator storage causes meaningful
  overhead after the arithmetic kernels are improved.

## Testing Requirements

Every optimization stage must retain or extend:

1. Python float-to-quantized export validation.
2. Python integer inference to C++ inference parity.
3. Rebuilt evaluation to incremental evaluation parity.
4. White/black color inversion symmetry.
5. Generic to AVX2 exact-result parity.
6. Runtime `.bin` network to generated-header network parity.
7. Accumulator state restoration after move, undo, null move, capture,
   promotion, en passant, and castling.

For layout-only changes, exact integer output must remain identical.

For quantization changes, exact compatibility with old networks is not
required, but the exporter must report quantization drift on a validation
dataset and reject unsafe weights or out-of-range values.

## Recommended Implementation Order

The practical sequence is:

1. Add the evaluation microbenchmark.
2. Remove repeated clipping and scalar AVX2 product reductions without changing
   the format.
3. Measure and profile.
4. Design the normalized byte-activation quantization contract in Python.
5. Add `uint8_t` activations, `int8_t` dense weights, and exact generic parity.
6. Add the packed AVX2 dense kernel and load-time matrix repacking.
7. Measure strength and speed before changing accumulator storage.
8. Add `int16_t` accumulators with strict range validation.
9. Re-profile before deciding whether lazy accumulators are worth the larger
   implementation effort.

## Stage 1 Results

Stage 1 was implemented on branch `nnue-v3-dense-kernel` without changing the
network format, quantization, or evaluation results.

The dense scoring path now:

- clamps the active and passive accumulator lanes once into one contiguous
  dense input buffer
- performs one dense dot product per hidden neuron instead of two clipped lane
  dot products
- uses AVX2 `int32_t` to `int64_t` even/odd products and in-register reduction
  instead of storing products to memory and summing them scalarly

The benchmark net was:

```text
/home/nicu/NNUE/runs/g3hl1/chilo-g3hl1.bin
contract: chilo.tiny_nnue.v4
dimensions: 64 -> 32 -> 1
input_scale: 256
hidden_scale: 32
output_scale: 32
```

### Evaluator microbenchmark

`nnue_eval_bench` used its built-in eight-position corpus, 300000 passes, and
three measured runs per binary. The table reports median evaluations per
second. All variants produced the same checksum.

| Build and mode | Before | After | Change |
| --- | ---: | ---: | ---: |
| generic rebuilt | 187099 | 237953 | +27.18% |
| generic incremental | 273579 | 395470 | +44.55% |
| AVX2 rebuilt | 236397 | 435439 | +84.20% |
| AVX2 incremental | 398081 | 1499812 | +276.76% |

Example command:

```sh
build/release-avx2/nnue_eval_bench \
    --weights /home/nicu/NNUE/runs/g3hl1/chilo-g3hl1.bin \
    --passes 300000 \
    --mode both
```

### Fixed-depth AVX2 search

The existing fixed-depth benchmark compared preserved pre-change and
post-change AVX2 binaries with the same `g3hl1` runtime net.

Default three-position workload, depth 10, five measured runs after one
warm-up:

| Metric | Before | After | Change |
| --- | ---: | ---: | ---: |
| total nodes | 1412457 | 1412457 | 0.00% |
| total engine time | 4358 ms | 1852 ms | -57.50% |
| weighted NPS | 324106 | 762665 | +135.31% |

```sh
python3 scripts/benchmark_fixed_depth.py \
    --baseline /tmp/chilo-nnue-v3-stage1-baseline/chilo-avx2 \
    --candidate build/release-avx2/chilo \
    --weights /home/nicu/NNUE/runs/g3hl1/chilo-g3hl1.bin \
    --depth 10 \
    --runs 5 \
    --warmups 1 \
    --output-dir /tmp/chilo-bench/nnue-v3-stage1-default
```

First 50 positions from `open-moves.fen`, depth 8, one measured run:

| Metric | Before | After | Change |
| --- | ---: | ---: | ---: |
| total nodes | 11708156 | 11708156 | 0.00% |
| total engine time | 37103 ms | 16170 ms | -56.42% |
| weighted NPS | 315558 | 724066 | +129.46% |

```sh
python3 scripts/benchmark_fixed_depth.py \
    --baseline /tmp/chilo-nnue-v3-stage1-baseline/chilo-avx2 \
    --candidate build/release-avx2/chilo \
    --weights /home/nicu/NNUE/runs/g3hl1/chilo-g3hl1.bin \
    --fen-file /home/nicu/Tune/open-moves/open-moves.fen \
    --max-positions 50 \
    --depth 8 \
    --runs 1 \
    --warmups 0 \
    --output-dir /tmp/chilo-bench/nnue-v3-stage1-open-moves
```

Both search workloads retained identical node counts, best moves, and detailed
search statistics. This confirms that Stage 1 is a pure inference speed
improvement.
