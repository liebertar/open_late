// Pattern service: FreeSewing designs -> 1:1 SVG in mm (seam allowance, notches, grainlines, fold marks).
//   GET  /health
//   GET  /designs                      required/optional measurements per design
//   POST /draft {design, size | measurements, sa?, options?}  -> {svg, measurements, logs}
//   GET  /bodies                       body measurement sets of the people who wear each size
import http from 'node:http'
import fs from 'node:fs'
import { Hugo } from '@freesewing/hugo'
import { Sven } from '@freesewing/sven'
import * as models from '@freesewing/models'

const DESIGNS = { hugo: Hugo, sven: Sven }
const SIZES = JSON.parse(fs.readFileSync(new URL('./sizes.json', import.meta.url)))
const PORT = Number(process.env.PORT || 7110)

function measurementsFor(size) {
  const s = SIZES.sizes[size]
  if (!s) throw new Error(`unknown size "${size}" (have: ${Object.keys(SIZES.sizes).join(', ')})`)
  const base = models[s.base]?.[s.model]
  if (!base) throw new Error(`model set ${s.base}[${s.model}] not found in @freesewing/models`)
  return { ...base, ...(s.override || {}) }
}

function draft({ design = 'hugo', size, measurements, sa = 10, options = {} }) {
  const Design = DESIGNS[design]
  if (!Design) throw new Error(`unknown design "${design}" (have: ${Object.keys(DESIGNS).join(', ')})`)
  const m = measurements || measurementsFor(String(size))
  const pattern = new Design({ measurements: m, sa, expand: true, options }).draft()
  const logs = typeof pattern.getLogs === 'function' ? pattern.getLogs() : (pattern.stores?.[0]?.logs || {})
  return { design, size: size ?? null, sa, measurements: m, svg: pattern.render(), logs }
}

function send(res, code, body) {
  res.writeHead(code, { 'content-type': 'application/json' })
  res.end(JSON.stringify(body))
}

http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') return send(res, 200, { ok: true })
  if (req.method === 'GET' && req.url === '/designs') {
    const out = {}
    for (const [name, D] of Object.entries(DESIGNS)) {
      const cfg = new D().getConfig()
      out[name] = { required: cfg.measurements, optional: cfg.optionalMeasurements, parts: Object.keys(cfg.parts || {}) }
    }
    return send(res, 200, { designs: out, sizes: SIZES })
  }
  if (req.method === 'GET' && req.url === '/bodies') {
    const out = {}
    for (const [gender, sizes] of Object.entries({ male: SIZES.people.male, female: SIZES.people.female })) {
      const set = gender === 'male' ? models.cisMaleAdult : models.cisFemaleAdult
      out[gender] = Object.fromEntries(Object.entries(sizes).map(([size, key]) =>
        [size, { ...set[key], height: SIZES.people.height_mm[gender][size], set: key }]))
    }
    return send(res, 200, { bodies: out, sizes: Object.keys(SIZES.sizes) })
  }
  if (req.method === 'POST' && req.url === '/draft') {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => {
      try {
        send(res, 200, draft(JSON.parse(raw || '{}')))
      } catch (e) {
        send(res, 400, { error: e.message })
      }
    })
    return
  }
  send(res, 404, { error: 'not found' })
}).listen(PORT, () => console.log(`pattern service on :${PORT}`))
