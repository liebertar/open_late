"""Prototype of node-4 pattern verification. Usage: verify_pattern.py spec_s1.json spec_s2.json spec_s3.json"""
import json, sys, math
import numpy as np

def bez(pts, n=64):
    t = np.linspace(0, 1, n)[:, None]
    if len(pts) == 3:
        p0, p1, p2 = pts; return (1-t)**2*p0 + 2*(1-t)*t*p1 + t**2*p2
    p0, p1, p2, p3 = pts
    return (1-t)**3*p0 + 3*(1-t)**2*t*p1 + 3*(1-t)*t**2*p2 + t**3*p3

def edge_poly(v, e):
    s, t = np.array(v[e['endpoints'][0]], float), np.array(v[e['endpoints'][1]], float)
    c = e.get('curvature')
    if not c: return np.stack([s, t]), 'line'
    d = t - s; nrm = np.array([-d[1], d[0]])
    if c['type'] in ('quadratic', 'cubic'):
        cps = [s + p[0]*d + p[1]*nrm for p in c['params']]
        return bez([s, *cps, t]), c['type']
    if c['type'] == 'circle':
        r, large, _ = c['params']; ch = float(np.linalg.norm(d))
        th = 2*math.asin(min(1.0, ch/(2*r)))
        if large: th = 2*math.pi - th
        ang = np.linspace(0, 1, 64)[:, None]   # exact length; polyline only used for length here
        L = r*th
        return np.stack([s, s + d*(L/ch)]), 'circle'
    return np.stack([s, t]), c['type'] + '(approx-chord)'

def length(poly): return float(np.sum(np.linalg.norm(np.diff(poly, axis=0), axis=1)))

def check(spec_path):
    pat = json.load(open(spec_path))['pattern']; res = {'fails': [], 'warns': []}
    lens = {}
    for name, p in pat['panels'].items():
        E = p['edges']
        for i, e in enumerate(E):
            nxt = E[(i+1) % len(E)]
            if e['endpoints'][1] != nxt['endpoints'][0]:
                res['fails'].append(f'{name}: open contour at edge {i}')
            poly, kind = edge_poly(p['vertices'], e); lens[(name, i)] = length(poly)
            if 'approx' in kind: res['warns'].append(f'{name}.e{i}: {kind}')
    for st in pat['stitches']:
        a, b = st; la, lb = lens[(a['panel'], a['edge'])], lens[(b['panel'], b['edge'])]
        if abs(la - lb) > 0.2:   # cm  (2 mm)
            res['fails'].append(f"stitch {a['panel']}.e{a['edge']}({la:.1f}) <-> {b['panel']}.e{b['edge']}({lb:.1f}) diff {abs(la-lb)*10:.1f}mm")
    res['panels'] = sorted(pat['panels']); res['stitchset'] = sorted(tuple(sorted((x['panel'] for x in s))) for s in pat['stitches'])
    res['width'] = {n: float(np.ptp(np.array(p['vertices'])[:, 0])) for n, p in pat['panels'].items()}
    blob = json.dumps(pat).lower()
    for feat in ('allowance', 'notch', 'grain'):
        if feat not in blob: res['fails'].append(f'production feature missing: {feat}')
    return res

if __name__ == '__main__':
    paths = sys.argv[1:]; R = [check(p) for p in paths]
    for p, r in zip(paths, R):
        print(f"\n== {p.split('/')[-1]}  fails={len(r['fails'])} warns={len(r['warns'])}")
        for f in r['fails'][:12]: print('  FAIL', f)
        for w in r['warns'][:3]: print('  warn', w)
    print('\n== cross-size')
    print('  panel names identical:', all(r['panels'] == R[0]['panels'] for r in R))
    for i in range(1, len(R)):
        a, b = set(R[0]['stitchset']), set(R[i]['stitchset'])
        print(f'  stitch topology s1 vs s{i+1}: +{len(b-a)} -{len(a-b)}', (list(b-a)+list(a-b))[:4])
    mono = [n for n in R[0]['width'] if not (R[0]['width'][n] <= R[1]['width'][n] <= R[2]['width'][n])]
    print('  panels violating width 1<=2<=3:', mono or 'none')
