#!/usr/bin/env python3
"""
Pixel-compare every PNG in a folder against Base.png.
If the pixels match, set flip=true for the matching entry in cluster.json.

Usage:
    python check_antler_flip.py [--folder .] [--json cluster.json] [--ref Base.png]

Example:
    python check_antler_flip.py --folder ./skins --json cluster.json
"""

import argparse
import json
import sys
from pathlib import Path
from PIL import Image


def images_match(img_a: Image.Image, img_b: Image.Image, tolerance: int = 0) -> tuple[bool, float]:
    """
    Compare two images pixel-by-pixel (after resizing img_a to img_b's size if needed).
    Returns (matched: bool, match_pct: float).
    Only non-transparent pixels in the reference (img_b) are compared.
    `tolerance` allows per-channel difference of up to this value (0 = exact).
    """
    a = img_a.convert("RGBA")
    b = img_b.convert("RGBA")

    if a.size != b.size:
        a = a.resize(b.size, Image.NEAREST)

    pixels_a = list(a.getdata())
    pixels_b = list(b.getdata())

    compared = 0
    matched = 0

    for pa, pb in zip(pixels_a, pixels_b):
        if pb[3] == 0:
            continue
        compared += 1
        if all(abs(int(ca) - int(cb)) <= tolerance for ca, cb in zip(pa[:3], pb[:3])):
            matched += 1

    if compared == 0:
        return False, 0.0

    pct = matched / compared
    return pct == 1.0, pct


def update_cluster(json_path: Path, name: str, flip_value: bool) -> bool:
    """Find the entry by name in cluster.json and update its flip field. Returns True if found."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    found = False
    for artifact in data.get("artifacts", []):
        if str(artifact.get("name")) == str(name):
            artifact["flip"] = flip_value
            found = True
            break

    if found:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    return found


def derive_name(png_path: Path) -> str:
    """
    Strip trailing space+digits from the filename stem to get the cluster.json name.
    e.g. 'Wumpus 204' -> 'Wumpus', 'Yellow Glorious Wings 196' -> 'Yellow Glorious Wings',
         'Wumpus King Costume C17' -> 'Wumpus King Costume C17' (no change, ends in letters).
    """
    import re
    stem = png_path.stem
    return re.sub(r' \d+$', '', stem)


def main():
    parser = argparse.ArgumentParser(
        description="Compare every PNG in a folder against Base.png and update cluster.json"
    )
    parser.add_argument(
        "--folder", default=".",
        help="Folder containing the skin PNGs (default: current directory)"
    )
    parser.add_argument(
        "--ref", default="Base.png",
        help="Reference image to compare against (default: Base.png)"
    )
    parser.add_argument(
        "--json", dest="json_path", default="cluster.json",
        help="Path to cluster.json (default: cluster.json)"
    )
    parser.add_argument(
        "--tolerance", type=int, default=0,
        help="Per-channel pixel tolerance 0-255 (default: 0 = exact)"
    )
    args = parser.parse_args()

    folder    = Path(args.folder)
    ref_path  = Path(args.ref) if Path(args.ref).is_absolute() else folder / args.ref
    json_path = Path(args.json_path)

    # --- Validate ---
    if not folder.is_dir():
        print(f"ERROR: Folder not found: {folder}", file=sys.stderr)
        sys.exit(1)
    if not ref_path.exists():
        print(f"ERROR: Reference image not found: {ref_path}", file=sys.stderr)
        sys.exit(1)
    if not json_path.exists():
        print(f"ERROR: cluster.json not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    # --- Collect PNGs (skip the reference itself) ---
    all_pngs = sorted(
        p for p in folder.glob("*.png")
        if p.resolve() != ref_path.resolve()
    )

    if not all_pngs:
        print(f"No PNG files found in {folder} (excluding {ref_path.name}).")
        sys.exit(0)

    ref_img = Image.open(ref_path)
    print(f"Reference  : {ref_path}  ({ref_img.size[0]}x{ref_img.size[1]})")
    print(f"Tolerance  : {args.tolerance} per channel")
    print(f"PNGs found : {len(all_pngs)}")
    print("=" * 60)

    results = {"matched": [], "no_match": [], "not_in_json": []}

    for png_path in all_pngs:
        skin_img = Image.open(png_path)
        matched, pct = images_match(skin_img, ref_img, tolerance=args.tolerance)
        name = derive_name(png_path)

        status = "✅ MATCH" if matched else "❌ NO MATCH"
        print(f"{png_path.name:<40}  {pct*100:6.2f}%  {status}  (name: {name})")

        if matched:
            found = update_cluster(json_path, name, flip_value=True)
            if found:
                results["matched"].append(png_path.name)
                print(f"    → cluster.json updated: name='{name}' flip: true")
            else:
                results["not_in_json"].append(png_path.name)
                print(f"    ⚠️  name='{name}' not found in cluster.json — skipped")
        else:
            results["no_match"].append(png_path.name)

    print("=" * 60)
    print(f"Summary:")
    print(f"  Matched & updated : {len(results['matched'])}")
    print(f"  Matched, missing  : {len(results['not_in_json'])}")
    print(f"  No match          : {len(results['no_match'])}")


if __name__ == "__main__":
    main()