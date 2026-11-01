# OPEN LATE

A gender-neutral basics brand that turns the comfort of a sign still lit late at night into clothes. AI nodes handle everything from design to operations,
and people only contact the sample room and factories and give approvals. The runtime uses only open models and scripts.

## Start it up

```bash
cp .env.example .env
make up          # whole docker stack: console · pattern · worker · mlflow
make gateway     # host model gateway (MLX, :8090). Downloads ~20GB on first run
```

| Stack | Address | What it does |
|---|---|---|
| console | http://localhost:7100 | Node board, approval gates, rejection reasons, history |
| fitting room | http://localhost:7100/fitting | Choose a size: fit preference, two-size answer, fit in words |
| fit QA | http://localhost:7100/fitting/qa | Internal: grading lineups, model upkeep, engine status |
| pattern | http://localhost:7110/designs | FreeSewing (Hugo hoodie · Sven sweatshirt) → 1:1 SVG (mm), seam allowance, notches, grain, fold lines |
| worker | http://localhost:7120/health | SVG → DXF (AAMA layers, R12) + automated checks |
| mlflow | http://localhost:5060 | Per-node duration, check pass rate, model A/B records |
| model-gateway | http://localhost:8090 | **Native on the host**. Qwen3.6-35B-A3B (text + vision) |

Models don't go in Docker, because Docker on macOS can't use the Metal GPU. Containers call the host gateway at
`host.docker.internal:8090`.

## Structure

```
open_late/
├─ compose.yaml          ties stacks/*/compose.yaml together with include → one docker compose up
├─ Makefile              up · full · gateway · ps · logs · down
├─ pipeline/nodes.yaml   defines 16 nodes (13 from the brief + 3 added), gate types, review bundles
├─ stacks/
│  ├─ console/           FastAPI. State machine + append-only history.jsonl + rules.md
│  ├─ pattern/           Node. FreeSewing 4.10.2
│  ├─ worker/            Python. ezdxf · svgpathtools. Check rules are in checks.py
│  └─ observability/     MLflow (+ MinIO, profile full)
├─ host/model-gateway/   script that runs the MLX server (outside Docker)
├─ data/                 state · history · outputs (not in git)
├─ docs/                 review.md (pipeline review) · architecture.md
├─ experiments/          01 GarmentCode evaluation · 02 colorway board · 03 base layer · 04 draped geometry
└─ research/sml-lab      git submodule. Model and training lab (try-on, surveys)
```

Each stack is self-contained in its own folder, so it can be split out into a separate repo or submodule later.

## What works now

- Node 4 (pattern): run from the console → SVG + DXF + `checks.json` for sizes 1, 2, and 3. Hugo currently passes 148 of 154 checks.
  The pocket facing has no grainline and its cut line is open, so **the gate blocks it** (intended behavior).
- Approval gate: the Approve button stays locked until the automated checks pass (the API also returns 409).
- Rejection reasons are saved to `data/rules.md`, and every run, approval, and rejection is saved to `data/history.jsonl`.

## Not there yet

- Sizes 1, 2, and 3 are temporarily mapped to FreeSewing standard bodies (cisMaleAdult 38/42/46). We still need a step that works back from the finished measurements in spec.json to body measurements + ease.
- A "production layer" for things like grainline correction, plus notch direction and round-trip comparison with the sample room's DXF
- Runners for nodes 1, 2, 3, and 5-13

See `docs/review.md` for the detailed reasoning.
