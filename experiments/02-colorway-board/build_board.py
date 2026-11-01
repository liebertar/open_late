"""Build the colorway board page from colorways.json + out/*.png + out/measure.json.

    python build_board.py <experiment_dir> <site_dir>
"""
import html
import json
import shutil
import sys
from pathlib import Path

E, SITE = Path(sys.argv[1]), Path(sys.argv[2])
cfg = json.load(open(E / "colorways.json"))
measure = json.load(open(E / "out" / "measure.json")) if (E / "out" / "measure.json").exists() else {}
(SITE / "img").mkdir(parents=True, exist_ok=True)
shutil.copy(E / "colorways.json", SITE / "colorways.json")  # the console's fitting room reads garments from here

cards = []
for c in cfg["colorways"]:
    imgs = []
    for kind, label in (("product", "Product shot"), ("onmodel", "On-model shot · Virtual model")):
        src = E / "out" / f"{c['id']}_{kind}.png"
        if src.exists():
            shutil.copy(src, SITE / "img" / src.name)
            imgs.append(f'<figure><img src="img/{src.name}" alt="{html.escape(c["outer"])} × {html.escape(c["lining"])} {label}" '
                        f'loading="lazy"><figcaption>{label}</figcaption></figure>')
    m = measure.get(c["id"], {})
    de = m.get("delta_e00")
    verdict = "" if de is None else ("Close" if de < 5 else "Large difference" if de >= 10 else "Noticeable difference")
    cls = "" if de is None else ("good" if de < 5 else "bad" if de >= 10 else "mid")
    cards.append(f"""
<article class="cw">
  <header>
    <div class="pair"><span class="sw" style="background:{c['outer_hex']}"></span><span class="sw" style="background:{c['lining_hex']}"></span></div>
    <div><h2>{html.escape(c['outer'])} <span>×</span> {html.escape(c['lining'])}</h2>
    <p class="hex mono">Outer fabric {c['outer_hex']} · lining and bartack thread {c['lining_hex']}</p></div>
  </header>
  <div class="shots">{''.join(imgs)}</div>
  <div class="color">
    <div class="cmp"><span class="sw sm" style="background:{c['outer_hex']}"></span><span class="mono">Target {c['outer_hex']}</span></div>
    <div class="cmp"><span class="sw sm" style="background:{m.get('rendered_hex', 'transparent')}"></span><span class="mono">Render {m.get('rendered_hex', '—')}</span></div>
    <div class="de {cls}"><b class="mono">ΔE00 {de if de is not None else '—'}</b> {verdict}</div>
  </div>
</article>""")

page = (Path(__file__).parent / "board_template.html").read_text()
page = page.replace("{{CARDS}}", "".join(cards)).replace("{{NOTE}}", html.escape(cfg["note"]))
(SITE / "index.html").write_text(page)
print("board written:", SITE / "index.html", f"({len(cards)} colorways)")
