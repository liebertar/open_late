"""Write GarmentCode panels to DXF (mm, AAMA-style layer names) and round-trip check."""
import json, sys, math, numpy as np, ezdxf
sys.path.insert(0, sys.argv[3]); from verify_pattern import edge_poly, length
spec, out = sys.argv[1], sys.argv[2]
pat = json.load(open(spec))['pattern']
doc = ezdxf.new('R12')  # R12 has no $INSUNITS header; AAMA declares units as text
msp = doc.modelspace(); src = {}
msp.add_text('UNITS = METRIC', dxfattribs={'layer': '1'})
for name, p in pat['panels'].items():
    pts = []
    for e in p['edges']:
        poly, kind = edge_poly(p['vertices'], e)
        if kind == 'circle':   # re-sample true arc for geometry
            s, t = poly[0], np.array(p['vertices'][e['endpoints'][1]], float)
            r, large, right = e['curvature']['params']; ch = np.linalg.norm(t - s)
            th = 2*math.asin(min(1, ch/(2*r))); th = 2*math.pi - th if large else th
            mid = (s+t)/2; nrm = np.array([-(t-s)[1], (t-s)[0]])/ch; h = math.sqrt(max(r*r-(ch/2)**2, 0))
            c = mid + nrm*h*(1 if right else -1)
            a0, a1 = math.atan2(*(s-c)[::-1]), math.atan2(*(t-c)[::-1])
            d = (a1 - a0) % (2*math.pi); d = d - 2*math.pi if abs(d - th) > 1e-3 and abs(d - 2*math.pi + th) < abs(d - th) else d
            angs = np.linspace(a0, a0 + d, 48); poly = np.stack([c + r*np.array([math.cos(a), math.sin(a)]) for a in angs])
        pts.extend((poly[:-1]*10).tolist())        # cm -> mm
    src[name] = length(np.vstack([pts, pts[:1]]))
    msp.add_polyline2d(pts, close=True, dxfattribs={'layer': '1'})        # AAMA layer 1 = boundary
    msp.add_text(name, dxfattribs={'layer': '15', 'height': 10})           # piece name annotation (placeholder)
doc.saveas(out)
back = ezdxf.readfile(out); got = {}
names = list(src)
for i, pl in enumerate(back.modelspace().query('POLYLINE')):
    v = [tuple(x.dxf.location)[:2] for x in pl.vertices]; v.append(v[0])
    got[names[i]] = float(sum(math.dist(a, b) for a, b in zip(v, v[1:])))
worst = max(abs(src[n] - got[n]) for n in names)
print(f'{out.split("/")[-1]}: {len(names)} panels, max perimeter round-trip error {worst:.4f} mm')
