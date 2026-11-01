# 03: Base layer and numeric hem

Can a render follow the pattern if the prompt states the hem position in centimetres?

Setup: two bodies, the Ink navy × Apricot hoodie, sizes XS to XL, seed 42, FLUX.2 klein 4B edit at 4 steps. Each model
was first dressed in a white t-shirt, grey trousers and white sneakers, then the hoodie went on top with a hem sentence
placed first in the prompt, stating the garment length and the distance from the crotch. The script writes only to
`data/fitting/bakeoff/base-layer` and leaves production portraits and try-ons alone.

Run with the console and render engine up, from the repo root:

    uv run --no-project --python 3.12 --with pyyaml==6.0.2 python experiments/03-base-layer-ladder/ladder.py

## Result (2026-11-01)

| Body | Hem travel XS to XL | Pattern | Share |
|---|---|---|---|
| Man, 175 cm | 2.3 cm | 15.9 cm | 14% |
| Woman, 160 cm | 1.9 cm | 15.9 cm | 12% |

The hem was measured from the staged images as the lowest row with more than 60 dark navy pixels in the middle 100
columns. An earlier count over the whole row picked up the cuffs and gave 0.4 and 4.2 cm; those figures are wrong.
Production renders of the same garment, measured the same way, travel 6.9 cm (man) and 7.5 cm (woman), so the numeric
sentence did worse than the plain prompt.

- The base layer works. Trousers and a t-shirt read as a normal outfit, and the dressing pass took 27 s per model.
- The numeric hem does not work. The model settles on one hoodie length and ignores the number, so sizes from S up come
  out up to 18.8 cm shorter than asked.
- The renders fail the hem gate, so the fitting room compares sizes by numbers and states that the images do not show
  the difference accurately.

Sentences cannot carry garment length with this model. The next attempt should fix the geometry first, for example by
stretching the garment region to the pattern's length and passing that to a low-strength edit, instead of asking for it
in words.
