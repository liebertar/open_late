#!/usr/bin/env bash
# Colorway board: product shot (text->image, fixed seed) + on-model shot (2-reference edit) per colorway.
set -euo pipefail
E="$(cd "$(dirname "$0")" && pwd)"; AVATAR="${AVATAR:?path to avatar.png}"
SEED=7
PROMPTS="$E/../../pipeline/prompts"
# fill a registry template: prompt <id> key=value ...
prompt() { python3 - "$PROMPTS/$1.yaml" "${@:2}" <<'PY'
import sys, yaml
t = yaml.safe_load(open(sys.argv[1]))["template"]
print(" ".join(t.format(**dict(a.split("=", 1) for a in sys.argv[2:])).split()))
PY
}
CONSOLE="${CONSOLE:-http://127.0.0.1:7100}"
# Progress goes to the console's job panel; rendering still works if the console is down.
post() { curl -sf -X POST -H 'content-type: application/json' "$CONSOLE$1" -d "$2" 2>/dev/null || true; }
TOTAL=$(python3 -c "import json;print(2*len(json.load(open('$E/colorways.json'))['colorways']))")
JOB=$(post /api/jobs "{\"name\":\"n09 Colorways render\",\"node\":\"n09\",\"total\":$TOTAL}" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])" 2>/dev/null || true)
DONE=0
PRODUCT_S=(); ONMODEL_S=()   # wall seconds per image, reported as the node's average timing
now() { python3 -c 'import time;print(time.time())'; }
step() { DONE=$((DONE+1)); [ -n "$JOB" ] && post "/api/jobs/$JOB" "{\"done\":$DONE,\"message\":\"$1\"}" >/dev/null; }
python3 -c "import json;[print('\t'.join([c['id'],c['outer_en'],c['outer_hex'],c['lining_en'],c['lining_hex']])) for c in json.load(open('$E/colorways.json'))['colorways']]" |
while IFS=$'\t' read -r id outer ohex lining lhex; do
  prompt=$(prompt colorway.product outer="$outer" outer_hex="$ohex" lining="$lining" lining_hex="$lhex")
  t0=$(now)
  /usr/bin/time -p mflux-generate-flux2 --model flux2-klein-4b --quantize 4 --steps 4 --seed $SEED \
    --width 768 --height 1024 --prompt "$prompt" --output "$E/out/${id}_product.png" 2>&1 | grep -E '^real|saved|Error' || true
  PRODUCT_S+=("$(python3 -c "import time;print(round(time.time()-$t0,1))")")
  step "${id} product shot"
  t0=$(now)
  /usr/bin/time -p mflux-generate-flux2-edit --model flux2-klein-4b --quantize 4 --steps 4 --seed 42 \
    --width 768 --height 1024 --image-paths "$AVATAR" "$E/out/${id}_product.png" \
    --prompt "$(prompt colorway.onmodel outer="$outer" lining="$lining")" \
    --output "$E/out/${id}_onmodel.png" 2>&1 | grep -E '^real|saved|Error' || true
  ONMODEL_S+=("$(python3 -c "import time;print(round(time.time()-$t0,1))")")
  step "${id} on-model shot"
  echo "done: $id"
done

# Colour check + board, then report the run to node n09 for review.
python3 "$E/measure.py" "$E"
python3 "$E/build_board.py" "$E" "$E/../../docs/colorway-board"
SUMMARY=$(python3 -c "import json;m=json.load(open('$E/out/measure.json'));v=[x['delta_e00'] for x in m.values()];print(f'{len(v)} colorways rendered · outer fabric ΔE00 {min(v)}–{max(v)}')")
[ -n "$JOB" ] && post "/api/jobs/$JOB" "{\"status\":\"done\",\"message\":\"$SUMMARY\",\"link\":\"/colorways/\"}" >/dev/null
REPORT=$(python3 - "$E" "$SUMMARY" "${PRODUCT_S[*]}" "${ONMODEL_S[*]}" <<'PY'
import json, sys
E, summary = sys.argv[1], sys.argv[2]
avg = lambda xs: round(sum(map(float, xs.split())) / len(xs.split()), 1) if xs.split() else None
ids = [c["id"] for c in json.load(open(f"{E}/colorways.json"))["colorways"]]
print(json.dumps({"status": "needs_review", "summary": summary, "link": "/colorways/", "model": "FLUX.2 klein 4B",
                  "previews": [f"/colorways/img/{i}_{k}.png" for k in ("product", "onmodel") for i in ids],
                  "timing": [{"label": "Product shot", "avg": avg(sys.argv[3])}, {"label": "On-model shot", "avg": avg(sys.argv[4])}]},
                 ensure_ascii=False))
PY
)
post /api/nodes/n09/report "$REPORT" >/dev/null
