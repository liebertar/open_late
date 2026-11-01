# Architecture

## Three planes

| Plane | Where | What |
|---|---|---|
| State and checks | Docker (`compose.yaml`) | console, pattern, worker, mlflow. CPU is enough, and they can be brought back up at any time |
| Models | Native on the host (`host/model-gateway`) | Qwen3.6-35B-A3B, FLUX.2 klein 4B, SAM 3, OCR. Docker on macOS can't use the Metal GPU |
| Experiments | `research/sml-lab` (submodule) | Model evaluation, training, surveys. Only the results enter the pipeline |

## Principles

- **spec.json is the single source of truth.** PDF · XLSX · SVG · DXF are derived from it in code.
- **Everything generated must be checked.** Automated check results open the approval gate.
- **Nodes exchange data only through files.** `data/runs/<run>/`. Input hashes are kept in the history.
- **Models don't make the call.** Code decides measurements, grading, cost, and tolerance pass or fail. Models produce wording and options.

## Should we split frontend and backend?

No. The real boundary is **app ↔ model**. Models need a GPU, are slow, and run asynchronously.
If we add our own direct-to-consumer store (DTC), it comes in as a single `stacks/shop/`, with FE and BE together inside it.
