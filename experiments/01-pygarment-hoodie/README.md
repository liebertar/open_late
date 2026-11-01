# 01-pygarment-hoodie

Minimal experiment for node 4 (pattern generation) in the brief. Uses GarmentCode (pygarment) to make a hoodie in sizes 1, 2, and 3,
runs the verification script, writes a DXF with ezdxf, then reads it back to check the round trip. 2026-10-11, Mac Studio M4 Max.

## Run

```bash
# GarmentCode repo (the design library is only in the repo, not in the pip package)
git clone --depth 1 https://github.com/maria-korosteleva/GarmentCode.git gc
uv venv --python 3.11 .venv && source .venv/bin/activate && uv pip install pygarment ezdxf
# PNG/PDF rendering needs the system libcairo (brew install cairo). Without it, stub out cairosvg and generate JSON/SVG only
cd gc && python ../hoodie_gen.py . ../out
python verify_pattern.py out/hoodie_s{1,2,3}/hoodie_s*_specification.json
python to_dxf.py out/hoodie_s2/hoodie_s2_specification.json out/hoodie_s2.dxf .
```

The design is `collar.component.style = Hood2Panels` and `sleeve.length = 1.0` on top of `t-shirt.yaml`.
Sizes are a rough grading that multiplies body measurements (bust·waist·hips·shoulder_w) by 0.95/1.0/1.05.

## Results

| Check | Result |
|---|---|
| Install and run on Apple Silicon | Works (pygarment 2.0.2, MIT, Python 3.11) |
| Generate sizes 1, 2, 3 | Works. 10 panels each, no self-intersection |
| Closed curves | All panels pass |
| Seam length match (±2mm) | All seams pass (when arcs are computed exactly) |
| Panel names across sizes | Identical |
| Seam topology across sizes | **Mismatch**: 2 extra `ftorso–sleeve_b` seams in sizes 2 and 3 only (20 → 22) |
| Size order 1≤2≤3 | Back width is 25.0cm in all 3 sizes, because the experiment's grading didn't scale `back_width` |
| Seam allowance · notches · grainline | **None**. The concept doesn't exist anywhere in the GarmentCode repo |
| Pockets · ribs · hood lining · zippers | **None**. Not in the design library |
| Panel splits | Sleeves are front/back halves and the body is left/right halves. These are splits for simulation and differ from real cut units |
| Output formats | JSON · SVG · PNG · PDF. No DXF → written directly with ezdxf |
| DXF round trip | Perimeter error 0.0000mm. But R12 has no `$INSUNITS`, so units have to go in as text the way AAMA does |
| Drape sim | Needs the GarmentCode-only Warp fork. Source build, CPU only without CUDA |

## What we learned

- GarmentCode is a **simulation data generator**. We have to write the production pattern (seam allowance, notches, grain, fold lines, one-piece sleeve, ribs, pockets) as another layer on top.
- If you grade by body measurement ratios, a missed key passes silently. State grade rules per POM, and the verification script must always check size monotonicity.
- Changing parameters can change the seam topology. A check for identical topology across sizes is a required gate.
- The seam lengths that first looked 28-38mm off were an error in the verification script, which approximated arcs with chords. The verification script itself has to be tested against golden cases.
