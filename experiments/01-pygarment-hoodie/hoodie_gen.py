"""Minimal experiment: parametric hoodie (sizes 1/2/3) with GarmentCode on Apple Silicon."""
import sys, json, copy, yaml
from pathlib import Path
gc_root, out = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(gc_root))
from assets.garment_programs.meta_garment import MetaGarment
from assets.bodies.body_params import BodyParameters

design = yaml.safe_load(open(gc_root/'assets/design_params/t-shirt.yaml'))['design']
design['collar']['component']['style']['v'] = 'Hood2Panels'
design['sleeve']['length']['v'] = 1.0          # long sleeve
base_body = gc_root/'assets/bodies/mean_all.yaml'

for size, k in [('1', 0.95), ('2', 1.0), ('3', 1.05)]:
    body = BodyParameters(base_body)
    # crude grading: scale girths/widths, keep head & heights mostly
    for key in list(body.params.keys()):
        if any(t in key for t in ('waist', 'bust', 'hips', 'chest', 'shoulder_w', 'arm_pose')) and isinstance(body.params[key], (int, float)):
            if 'arm_pose' not in key: body.params[key] *= k
    body.eval_dependencies()
    g = MetaGarment(f'hoodie_s{size}', body, copy.deepcopy(design))
    p = g.assembly()
    folder = p.serialize(out, tag='', to_subfolder=True, with_3d=False, with_text=False, view_ids=False, with_printable=True)
    spec = json.load(open(Path(folder)/f'hoodie_s{size}_specification.json'))
    pat = spec['pattern']
    print(f'size {size}: panels={len(pat["panels"])} stitches={len(pat["stitches"])} self_intersect={g.is_self_intersecting()} -> {folder}')
