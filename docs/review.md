# OPEN LATE AI Pipeline Review

As of 2026-10-11. Scope: the AI pipeline (13 nodes) in the brief, `OPEN LATE 브랜드 기획서.pdf`.
Perspectives: development, operations, code, usability, and model fit per node. The runtime uses only open models or scripts.

The evidence is of three kinds: Hugging Face, GitHub, and PyPI metadata read directly, experiments run directly on this Mac Studio
(`experiments/01-pygarment-hoodie`), and secondary sources. Items with only secondary sources are marked "(secondary)", and items that could not be confirmed are marked "(unverified)".

---

## 0. Conclusion first

The backbone of the brief is sound. The structure stays as it is: spec.json as the single source of truth, script checks after generation, approval gates, and an append-only history.
Five things need to change.

1. **Switch the pattern engine from GarmentCode to FreeSewing.** GarmentCode is a data generator for simulation. Seam allowance, notches, grainlines, and grading don't exist as concepts anywhere in its code (checked directly). FreeSewing's hoodie design, Hugo, run headless on this Mac, already produced seam allowance, notches, grain, fold lines, and a cut list.
2. **The GarmentCode simulation in node 5 can't be used commercially.** The Warp fork the simulator depends on has a non-commercial license. Leaving the simulation comparison to a vision model is also a poor fit. Replace it with a deterministic check that measures the pattern geometry in code and compares it with the spec.
3. **Consolidate to one model and run it locally.** Qwen3.6-35B-A3B takes vision input natively (no separate 27B vision model needed). At 4bit it's 20GB, so it runs on this Mac. OpenRouter is used only as a fallback for outages.
4. **Don't use Kanana-2 (decided).** Its license requires a "Powered by Kanana" notice on related websites and UI, which clashes with the brand's tone. CS defaults to Qwen3.6-35B-A3B, and we pick by A/B test against Apache-2.0 Korean models (A.X-3.1, Gravity-30B-A5B).
5. **Add the two missing nodes.** These are the care and content label and product information notice (legally required labeling) and fabric and wash testing. Both derive from spec.json, but the pipeline has no place for them today.

---

## 1. Verdict by node

Fit: ◎ keep as is · ○ add to it · △ replacement recommended · ✕ not usable

| # | Node | Model/tool in the brief | Fit | Verdict and evidence | Recommendation |
|---|---|---|---|---|---|
| 1 | Brief and concepts | Qwen3.6 · FLUX.2 klein 4B | ○ | klein 4B is Apache-2.0 and needs no separate approval for commercial use. Measured on this Mac: edit in 34 seconds, 11.8GB peak | Keep the same model. Train a brand-style LoRA (mflux-train, klein base 4B) on 20-40 approved mood images |
| 2 | Flats and spec | Qwen3.6 (JSON) + script | ○ | The mlx-lm server doesn't enforce `response_format`/JSON schema (confirmed in the v0.32.0 source) | Schema-constrained decoding with outlines or xgrammar. **The LLM doesn't produce measurements.** Code applies the base measurement table + grade rules, and the LLM only picks from options |
| 3 | Fabric sourcing | Qwen3.6 + template | ◎ | Text generation + template, so the risk is low | Keep. Add the wash test requirements (§4) to the fabric spec items |
| 4 | Pattern generation | pygarment · ezdxf | △ | Direct experiment result: it runs on a Mac. But it has no seam allowance, notches, grain, or grading; sleeves split into front and back halves; and there are no pockets, ribs, or zippers. The seam topology also changed when the size changed (20 → 22 seams) | **FreeSewing** (MIT, v4.10.2, 2026-09). Hugo = hood + pocket + cuff + hem band, Sven = sweatshirt. 3 sets of body measurements = sizes 1, 2, 3. We write the DXF ourselves with ezdxf (§3). The half-zip is built in code by extending Sven |
| 5 | Pattern sim check | GarmentCode sim · Qwen3.6-27B vision | ✕ | The Warp fork for GarmentCode has a **non-commercial license**. On macOS there's a bug where the sim silently does nothing (issue #60). Having a VLM compare sim renders with flats is weak at precise geometric comparison | **Replace with a deterministic check.** Measure POMs (chest width, total length, sleeve length, hood height) from the pattern geometry in code and compare them with the spec. A drape preview is optional; if we use one, we build it directly on upstream NVIDIA Warp (Apache-2.0, confirmed running on Mac CPU). Update 2026-11-01: Warp 1.18 no longer ships a cloth module and has no Metal backend, so `experiments/04-draped-geometry` uses a small MLX solver |
| 6 | Construction spec selection | 3D viewer · I click | ○ | A 2D panel-click MVP works right away. FreeSewing SVGs have an id on every path | Phase 1 is 2D SVG edge click → ISO 4915 catalog. 3D comes later |
| 7 | Sample room handoff | Human | ◎ | — | Auto-generate the email draft + attachment package. A person does the sending |
| 8 | Sample QA | Measurement script · Qwen3.6-27B vision | △ | Photo measurement error is about 1cm (secondary), while the tolerance for knit tops is usually ±1-2cm. That's right on the borderline. There's no VLM benchmark for sewing defects, and zero-shot CLIP failed on fabric defects (secondary) | A person measures 6-8 POMs with a tape and enters them in a form, and photos (ArUco board + SAM 3) serve as a cross-check. For defects, AnomalyDINO (DINOv2, Apache-2.0, no training, just a few good samples) produces an anomaly heatmap → VLM checklist on the flagged areas only → human confirmation |
| 9 | Colorways | Mask + color conversion · klein 4B | ○ | Phone photo ΔE00 is 11.7-42.3 (2026 study, secondary). Color can't be finalized from photos. The brief is right to say "swatches make the final call" | Produce the actual colors with LCh conversion inside the mask (colour-science, BSD) and use klein only to explore direction. Approve lab dips with a spectrophotometer (CMC 2:1, D65/10°) and a light box |
| 10 | Factory order | Human | ◎ | — | The quote comparison xlsx is code |
| 11 | Inspection | PaddleOCR-VL · Qwen3.6-27B · script | ○ | PaddleOCR-VL is Apache-2.0 and Korean is explicitly listed | Keep OCR for checking the care label and the care and content label. A/B with the Korean-focused **GravityOCR-KO** (1.1B, MIT, 2026-09). Defects use the same stack as node 8 |
| 12 | Merchandising and CS | Kanana-2 / Qwen3.6 + rules | △ | The Kanana license requires a "Powered by Kanana" notice, a "Kanana" prefix on derivative model names, and a separate contract for API resale | A/B CS with Qwen3.6-35B-A3B or Apache-2.0 Korean models (SKT A.X-3.1, Trillion Gravity-30B-A5B). On-model shots using AI models need a "Virtual model" label from 2026-06-01 (KFTC guideline revision, secondary) |
| 13 | Trademark watch | KIPRIS Plus API | ○ | Each trademark API service needs its own usage application. The free quota is unverified | Keep. Similarity is decided in code by edit distance over Hangul jamo + English phonemes |

---

## 2. Model placement (zero frontier models, local first)

| Role | Model | License | 4bit size | Notes |
|---|---|---|---|---|
| Default text + vision | **Qwen3.6-35B-A3B** | Apache-2.0 | 20.4GB | Native VLM, fast because only 3B is active. Nodes 1, 2, 3, 5, 8, 11, 12 |
| Hard vision reads | Qwen3.8-27B | Apache-2.0 | 16.1GB | 2026-08 dense VLM. A/B against 35B-A3B on nodes 8 and 11 |
| Korean CS candidates | A.X-3.1 (34.7B) · Gravity-30B-A5B | Apache-2.0 | — | A/B against Qwen3.6-35B-A3B. Kanana is ruled out (final) |
| Image | FLUX.2 klein 4B | Apache-2.0 | ~10–13GB | 9B and the 9B-based try-on LoRAs are non-commercial, so we don't use them |
| OCR | PaddleOCR-VL-1.5 · GravityOCR-KO | Apache-2.0 · MIT | ~1–2GB | |
| Segmentation | SAM 3 (mlx-community/sam3-8bit) | SAM License (commercial use allowed, gated) | 1.04GB | |
| Anomaly detection | DINOv2 + AnomalyDINO | Apache-2.0 | Small | DINOv3 has its own license, so we stay on v2 until legal has checked it |
| Prohibited | EXAONE 4.5 | Non-commercial (NC) | — | Same as the brief |

Loaded together they take about 40GB, which leaves room in 128GB. **OpenRouter comes out of the default path.** The issue isn't cost (the estimate of $1.45 a month is right). The issue is data leaving the machine, so it stays as a fallback used only when the Mac is off.

**Constrained decoding is required.** The mlx-lm server doesn't enforce JSON schema. Nodes that produce spec.json · construction.json · product.json go through our own wrapper around outlines (1.3.3, `from_mlxlm`) or xgrammar (0.2.8, Metal bitmask). Output that breaks the schema can't be produced in the first place.

---

## 3. Pattern engine details (nodes 4, 5, 6)

### Direct experiment summary (`experiments/01-pygarment-hoodie`)

| Check | GarmentCode result |
|---|---|
| Install and run on Apple Silicon | Works |
| Generate a hoodie in 3 sizes | Works, 10 panels |
| Seam length match ±2mm | Pass |
| Seam allowance · notches · grainline | None (0 grep hits across the code) |
| Pockets · ribs · zippers | None |
| Seam topology across sizes | Mismatch (20 → 22) |
| Cut units | Sleeves split front/back, body split left/right |
| DXF | Not in the default output. Written with ezdxf, the round-trip error is 0.0000mm |
| Sim | Non-commercial Warp fork, macOS bug |

### FreeSewing (recommended engine)

- MIT. npm v4.10.2 (2026-09-13). The repository has moved to Codeberg.
- **Hugo**: raglan-sleeve hoodie. The parts are back · front · sleeve · pocket · pocketFacing · hoodSide · hoodCenter · waistband · cuff · neckBinding.
- **Sven**: sweatshirt. Both are based on the Brian block. Measurements: 13 required + 1 optional, going by Hugo.
- We rendered SVG headless on this Mac (Node 25). The output included 10mm seam allowance paths, notches (11 on Hugo), grainlines, fold marks, and a cut list. `@freesewing/config` and `plugin-transform` had to be installed manually.
- **Caution**: Hugo is raglan. If we want a set-in sleeve hoodie, we combine Sven (set-in) + Hugo's hood in code.
- **There is no DXF exporter.** We write it.

### FreeSewing local verification (2026-10-11, `stacks/pattern` + `stacks/worker`)

| Check | Result |
|---|---|
| Hugo · Sven, generate sizes 1, 2, 3 | No errors. Output SVG is mm 1:1 |
| Pieces | 10 for Hugo: front and back (on the fold), one-piece raglan sleeve, pocket, pocket facing, hood side and center, hem band, cuff, neck binding |
| Fabric breakdown | Hem band and cuff are marked `various` (rib fabric) → basis for the BOM |
| DXF conversion | Layers 1 cut line · 14 finished line · 4 notch · 7 grain · 6 fold line · 15 piece name |
| Automated checks | Hugo passes 148 of 154. **Failures: no grain/fold line on the pocket facing, and cut line ends left open outside the fold line.** Sven has no grain on the cuff and hem band |
| Piece set across sizes | Identical |
| Checker false positives | At first it flagged the open cut lines on cut-on-fold pieces (front, back, pocket) as failures. We fixed it to pass when the endpoints sit on the fold line |
| Remaining work | Finished measurements (spec.json) → work back to body + ease, correct missing grain, notch direction, round-trip comparison with the sample room's DXF |

### DXF writing rules

- Write R12 with ezdxf (MIT, 1.4.4). **R12 has no `$INSUNITS` header.** Put units in as text the way AAMA does and lock them to mm. This is exactly the spot the brief worried about: "unit errors creeping in silently".
- Layers follow the numbering in the source of Valentina (GPL, the open-source tool that actually exports AAMA/ASTM).

| Layer | AAMA | ASTM |
|---|---|---|
| 1 | Cut line | Pattern outline |
| 4 | Notch | V and slit notches |
| 7 | Grainline | Grainline |
| 8 | Internal line | Internal line |
| 14 | Seam line | Seam line |
| 15 | — | Annotation text |

- Valentina has commented out AAMA layers 19 and 26, saying one CAD vendor "doesn't like them". That's evidence that each vendor's CAD accepts files differently.
- As the comparison baseline (golden) and fallback, keep the Valentina CLI (`-f` AAMA=16, ASTM=25) as a separate process. It's GPL, so we only run it and don't link it.
- ASTM D6673-10 was withdrawn in 2019. Match the format the sample room actually accepts by **getting a sample DXF from them** (same as the brief).

### Pattern verification script (node 4 gate)

Extend the prototype run in the experiment (`verify_pattern.py`).

| Check | Criterion |
|---|---|
| Closed curves | Every piece outline is closed |
| Seam length match | Difference between paired seams ≤ 2mm. Where ease is intended, state the allowance in the spec |
| Units | Locked to mm, unit text present in the DXF |
| Notches · grainline | One grainline on every piece, notch count and position match on paired seams |
| Symmetry | Left and right pieces mirror each other |
| **Identical topology across sizes** | Piece and seam sets are the same for 1, 2, and 3 (this really did break in the experiment) |
| **Size monotonicity** | Every POM is 1 < 2 < 3 |
| POM comparison | Finished measurement taken from the pattern = spec measurement ± tolerance (replaces node 5) |
| Round trip | DXF write → read → perimeter, notches, and grain match |
| **Checker self-test** | Hand-calculated golden cases. In the experiment, approximating arcs with chords produced false failures of 28-38mm |

---

## 4. Missing nodes

| Added node | Reason | Output |
|---|---|---|
| **Care and content label and notice** | Household textile products fall under safety standard compliance. There's no KC certification, but labeling is mandatory. Items: fiber content, manufacturer/importer, country of manufacture, year and month of manufacture, size, handling precautions, address and phone. Product information notice on the detail page (secondary) | `care_label.pdf` · `product_notice.json` (generated from spec.json in code) |
| **Fabric and wash testing** | The brief's standard is "sturdy enough not to change in the wash", but no node measures it. ISO 6330 washing → ISO 5077 shrinkage, ISO 12945 pilling, ISO 105-C06 wash colorfastness, ISO 105-X12 rubbing. Example knit shrinkage standard: ±4-6% after 5 washes (secondary). Garment dyeing allows about 50% more tolerance (secondary) | `test_request.pdf` · `test_result.json` → fed back into the spec |
| **Grade rules** | In the experiment, scaling body measurements by ratio left the back width at 25.0cm in all 3 sizes. There was no warning at all | `grade_rules.json` (increments between sizes per POM) |
| **Eval set and regression** | Keeping approved patterns and measurements makes it possible to catch regressions when models or rules change (a "proposed" item in the brief) | `eval/` · MLflow records |

---

## 5. Operations

- **Single point of failure**: Every node runs on one Mac Studio. Batch nodes (1-11) are fine. But **CS (node 12) needs to respond at all times.** Requests go into a queue, when the Mac is off the OpenRouter fallback produces drafts only, and a person always does the sending.
- **Disk**: Today the HF cache reached 106GB and the disk hit 97%. Pin the model list in `models.lock` (name · revision · size) and clear any cache not on the list.
- **System dependencies**: GarmentCode crashed on PNG/PDF output without libcairo (brew). FreeSewing needed Node and 2 manually installed plugins. Pin all of this in a single setup script.
- **Model serving**: Keep Qwen3.6-35B-A3B resident in one process with the constrained decoding wrapper in front of it. Add a health check, and record model · revision · input hash to JSONL on every node run (same as the brief).
- **Observability**: Record per-node duration, check pass rate, and rejection reason counts in the already-running `ml-studio` (MLflow, localhost:5050).

## 6. Code

- **spec.json's JSON Schema is generated from a Pydantic model.** Constrained decoding, validation, and the console forms share the same schema. The rule that people don't edit the PDF is enforced in code.
- **Content-addressed cache**: A node's output path is set by its input hash. The same input isn't recomputed, and this ties in naturally with the input hashes in the history JSONL.
- **Keep the orchestrator light**: For 13 nodes in a DAG with approval gates, Airflow or Dagster is overkill. A file-based state machine (waiting · checks passed · checks failed · needs review · approved) and a `make`-style runner are enough.
- **Golden file tests**: Keep sample DXFs from the sample room, hand-calculated pattern measurements, and approved specs in `tests/fixtures/` along with their hashes.

## 7. Usability

- **9 approval gates are too many.** If a person has to press 9 of the 13, that goes against the brief's intent that "AI runs it". Real decisions cluster at three moments.
  1. Design review: approve nodes 1, 2, and 3 together on one screen
  2. Sample review: nodes 6 and 8
  3. Launch review: nodes 9 and 12
  - Nodes 7 and 10 aren't approvals but a "vendor reply received" check.
- **The approval screen holds only what's needed to decide.** An automated check summary (pass/fail counts), the diff from the previous version, and one line on "what is being decided". Reject means choosing from a list of reasons + free text, and these accumulate in rules.md.
- **Node 6 viewer**: Seam click → nobody should have to memorize stitch numbers to pick one. Prefill defaults by area. The defaults are industry practice, so mark them as assumptions until a vendor confirms them (unverified).
  - Body, sleeve, and hood seams 514
  - Hem and sleeve hem 406
  - Topstitch 301
- **Vendor contact**: Bring up the email draft + attachment zip + "questions to ask the vendor" all at once (§8).

## 8. Questions for the sample room and factories

1. Which CAD and DXF format they accept (AAMA / ASTM, AutoCAD version). Request 1 sample DXF
2. Units (mm/inch) and how the units are marked
3. Notch shape (V / slit / T) and layer
4. Whether they want seam allowance included or as a separate line
5. Who does grading and marking. Whether a grade rule file (.rul) is needed
6. 1:1 output method (tiled PDF / PLT / direct plotter)
7. How to mark fold pieces (opened-out piece vs half + fold mark)
8. Tolerance standard for sample measurements (per POM)

## 9. Training plan (what, and when)

We don't train an LLM from the start. We begin with prompts + constrained decoding + rule code, and **train on approval data once it has built up.**

| Target | Method | Start condition | Tool |
|---|---|---|---|
| Brand mood images | klein base 4B LoRA (rank around 16) | 20-40 approved mood images | mflux-train |
| Anomaly detection | No training. Memory bank from good sample photos | 20-50 good shots | AnomalyDINO + DINOv2 |
| Korean CS tone | LoRA SFT | 200-500 approved response pairs | mlx-lm lora |
| Spec writing | LoRA SFT (optional) | 50+ approved specs, accumulated rejection reasons | mlx-lm lora |
| Measurement | No training. ArUco + SAM 3 + landmarks | Fixed photo jig | Refer to the GarmentIQ structure (code MIT) |
| Evaluation | The approval history is the golden set. Regression on every change | Always | ml-studio MLflow |

Watch only: pattern generation models (ChatGarment, GarmentGPT, Design2GarmentCode, AIpparel) all output the GarmentCode format. So they have no seam allowance, notches, or DXF, and most assume CUDA. Use them only for experiments that pull drafts from reference photos, and keep them off the production path.

## 10. MVP order

1. Send sample room candidates the §8 questions + a sample DXF request
2. FreeSewing Hugo/Sven in 3 sizes → ezdxf DXF → verification script → round-trip comparison with the sample DXF
3. spec.json Pydantic schema + constrained decoding wrapper (Qwen3.6-35B-A3B local)
4. Review console: state machine + JSONL history + 3 bundled approval screens
5. Node 6 2D seam-click viewer → construction.json
6. Care and content label and notice generation, wash test request
7. Sample QA: measurement form + AnomalyDINO + VLM checklist
8. Colorways LCh conversion, merchandising, CS

## Facts to correct in the brief

- GLM-OCR is 0.9B, not 1.3B (model card). It isn't in the brief, but the sml-lab docs list it as 1.3B.
- Qwen3.6-27B isn't a separate vision version; the base model accepts images. The same goes for 35B-A3B, so no separate vision model is needed.
- We couldn't find the try-on LoRA for Klein 4B (xocialize) this time (unverified). The try-on LoRAs confirmed to exist are 9B-based, so they're non-commercial.
- GarmentoPIA's code isn't public yet. SwiftTailor has no links to code or weights.

## Sources (main)

- Models: https://huggingface.co/Qwen/Qwen3.6-35B-A3B · https://huggingface.co/Qwen/Qwen3.8-27B · https://huggingface.co/kakaocorp/kanana-2-30b-a3b-instruct-2601 · https://huggingface.co/LGAI-EXAONE/EXAONE-4.5-33B · https://huggingface.co/trillionlabs/GravityOCR-KO · https://huggingface.co/PaddlePaddle/PaddleOCR-VL
- Constrained decoding: https://dottxt-ai.github.io/outlines/latest/features/models/mlxlm/ · https://github.com/mlc-ai/xgrammar · https://github.com/ml-explore/mlx-lm/blob/v0.32.0/mlx_lm/server.py
- Patterns: https://github.com/maria-korosteleva/GarmentCode · https://github.com/maria-korosteleva/NvidiaWarp-GarmentCode · https://github.com/maria-korosteleva/GarmentCode/issues/60 · https://freesewing.eu/designs/hugo · https://gitlab.com/smart-pattern/valentina · https://pypi.org/project/ezdxf/ · https://store.astm.org/d6673-10.html
- QA and color: https://github.com/open-edge-platform/anomalib · AnomalyDINO (WACV 2025) · https://huggingface.co/facebook/sam3 · https://github.com/colour-science/colour · https://www.mdpi.com/2079-6374/16/10/559 · https://github.com/lygitdata/GarmentIQ
- Regulation: https://kats.go.kr/content.do?cmsid=553 · KFTC endorsement and testimonial review guideline revision (2026-06-01, secondary: https://ditoday.com) · https://plus.kipris.or.kr
- Testing and tolerance: Lindstrom knit requirements PDF · Colony Brands NF-6 (secondary)
