# Prompt registry

One file per prompt. The console reads these on every call, so editing a prompt needs no rebuild.
Every render records `id@version` and a hash of the final text in its sidecar `.json`.

## Fields

| field | meaning |
|---|---|
| `id` | stable name, `<area>.<purpose>` |
| `version` | bump on every wording change; add a `changelog` line saying why |
| `model` | the model this prompt is written for |
| `format` | the rules this model wants (below) |
| `template` | text with `{variables}` |
| `parts` | lookup tables the template draws from (per size, per gender, ...) |

## Format rules per model

**FLUX.2 klein 4B** (image; BFL FLUX.2 guide + fal klein guide, checked 2026-10-18)
- English prose. Subject first: subject → action/pose → style → context → lighting → camera. Earlier words weigh more.
- 30–80 words is the sweet spot; past ~100 words results get muddled.
- No negative prompts: FLUX.2 ignores "no X" / "not Y". Describe what you want instead ("sharp focus", not "no blur").
- Colours: put the word `color` and the hex next to the object it belongs to ("outer fabric color #1E2A44").
- Multiple references: name each image's role by position ("the person from the first image ... the hoodie from the second image").
- Edits keep their prior for garment proportions: "sleeves cover part of the hands" still rendered wrist-length cuffs. State
  the fit detail first and as what is visible ("the ribbed cuffs cover the backs of both hands up to the knuckles").
- JSON-structured prompts are documented for FLUX.2 pro/max; untested on klein here.

**Z-Image-Turbo 6B** (image, portraits; Tongyi-MAI model card + same-prompt bake-off, 2026-10-18)
- English prose, subject first, ~100 words is fine (Qwen3-4B text encoder reads long prompts without muddling).
- Guidance-distilled: no negative prompt and no CFG. Positive phrasing only, as with FLUX.2.
- Colours as words. It renders text well, so a hex code or a label in the prompt can end up printed in the picture.
- Photography words steer realism: "matte skin with fine visible texture", "soft even diffused daylight", camera and lens.
  "Glowing skin" and "high-key light" read as an oily sheen. A named light source ("window") gets drawn into the frame.
- 9 steps at 768x1024 (~38 s on M4 Max; q8 and bf16 run at the same speed).
- Body words are read literally and "fashion model" pulls every body toward lean and defined. "Runway" made size S as thin
  as XS; "average build" still came out with a six-pack. Describe the soft parts concretely ("soft slightly rounded
  stomach", "smooth untoned chest", "softly rounded thighs") and add the size label ("US men's size M", "US dress size 4").
- Check grading with the true-scale lineup strips (data/fitting/qa) and the visual QA workflow, not one photo at a time:
  adjacent sizes that look the same only show up side by side.

**Qwen3.6-35B-A3B** (text + vision; for spec, CS, QA nodes — none written yet)
- Chat messages (system + user). Korean output where a human reads it; English for machine fields.
- Anything parsed by code goes through a JSON Schema with constrained decoding (outlines / xgrammar); the prompt names the schema, it does not paste one.
