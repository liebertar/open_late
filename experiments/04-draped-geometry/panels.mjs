// size -> flattened seam polylines per part, one polyline per pattern segment
import fs from 'node:fs'
import { Hugo } from '@freesewing/hugo'
import * as models from '@freesewing/models'
const SIZES = { XS: '34', S: '38', M: '42', L: '46', XL: '50' }
const PARTS = ['hugo.front', 'hugo.back', 'hugo.sleeve', 'hugo.waistband', 'hugo.cuff', 'library.hoodSide', 'library.hoodCenter', 'hugo.pocket', 'hugo.neckBinding']
const bez = (a, c1, c2, b, n = 48) => Array.from({ length: n + 1 }, (_, i) => {
  const t = i / n, u = 1 - t
  return [u*u*u*a.x + 3*u*u*t*c1.x + 3*u*t*t*c2.x + t*t*t*b.x, u*u*u*a.y + 3*u*u*t*c1.y + 3*u*t*t*c2.y + t*t*t*b.y]
})
const out = {}
for (const [size, key] of Object.entries(SIZES)) {
  const p = new Hugo({ measurements: { ...models.cisMaleAdult[key] }, sa: 0, expand: true }).draft()
  const parts = p.parts[0]; out[size] = {}
  for (const name of PARTS) {
    const part = parts[name], ops = part.paths.seam.ops, segs = []
    let at = null, start = null
    for (const o of ops) {
      if (o.type === 'move') { at = o.to; start = o.to }
      else if (o.type === 'line') { segs.push([[at.x, at.y], [o.to.x, o.to.y]]); at = o.to }
      else if (o.type === 'curve') { segs.push(bez(at, o.cp1, o.cp2, o.to)); at = o.to }
      else if (o.type === 'close' && Math.hypot(at.x - start.x, at.y - start.y) > 1e-6) { segs.push([[at.x, at.y], [start.x, start.y]]); at = start }
    }
    out[size][name] = segs
  }
}
fs.writeFileSync('panels.json', JSON.stringify(out))
