#!/usr/bin/env python3
"""fitrelief CLI — turn FIT files in resources/ into printable relief tiles.

Examples:
  python make.py resources/600371130_ACTIVITY.fit --title 雄鹰线
  python make.py 600371130_ACTIVITY.fit --shape circle --title 雄鹰线
  python make.py --all                          # process every fit in resources/
  python make.py xxx.fit --preset square_modern --config configs/xxx.yaml
"""
import argparse, glob, os, sys
from fitrelief import TileConfig, load_yaml, merge, build_tile

ROOT = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(ROOT, "presets")


def resolve_fit(name):
    for cand in [name, os.path.join("resources", name),
                 os.path.join("resources", name + ".fit")]:
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(f"FIT not found: {name}")


def make_one(fit_path, args):
    stem = os.path.splitext(os.path.basename(fit_path))[0]
    layers = [{}]
    if args.preset:
        layers.append(load_yaml(os.path.join(PRESETS, args.preset + ".yaml")))
    if args.config:
        layers.append(load_yaml(args.config))
    cli = {k: v for k, v in dict(shape=args.shape, title=args.title,
                                 exaggeration=args.exaggeration).items() if v is not None}
    cfg = TileConfig.from_dict(merge(*layers, cli))
    out = args.out or os.path.join("output", stem + (f"__{cfg.shape}" if args.preset or args.shape else ""))
    print(f"== {stem}  shape={cfg.shape}  title={cfg.title or '(sport)'} -> {out}")
    rep = build_tile(fit_path, cfg, out, renders=not args.no_render)
    print(f"   size {rep['size_mm']} mm  watertight={all(rep['watertight'].values())}  "
          f"-> {out}/{stem}.3mf")
    return out


def main():
    ap = argparse.ArgumentParser(description="FIT -> 3D-printable relief tile")
    ap.add_argument("fit", nargs="?", help="FIT file (name or path; looks in resources/)")
    ap.add_argument("--all", action="store_true", help="process every fit in resources/")
    ap.add_argument("--shape", help="hexagon|square|octagon|triangle|pentagon|circle|...")
    ap.add_argument("--title", help="top label text (default: sport name)")
    ap.add_argument("--preset", help="preset name in presets/ (without .yaml)")
    ap.add_argument("--config", help="per-activity YAML override")
    ap.add_argument("--exaggeration", type=float, help="vertical relief multiplier")
    ap.add_argument("--out", help="output dir (default output/<stem>)")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    if args.all:
        fits = sorted(glob.glob("resources/*.fit") + glob.glob("resources/*.FIT"))
        if not fits:
            sys.exit("no FIT files in resources/")
        for f in fits:
            make_one(f, args)
    elif args.fit:
        make_one(resolve_fit(args.fit), args)
    else:
        ap.error("provide a FIT file or --all")


if __name__ == "__main__":
    main()
