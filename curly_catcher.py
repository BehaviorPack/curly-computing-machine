import os
import sys
import json
import base64
import hashlib
import re
import shutil
import requests
from datetime import date
from pathlib import Path
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

# ========== CONFIGURATION ==========
DATA_JSON = Path("cluster.json")

BASE_URLS = {
    "cape":     "https://app.zeqa.net/cosmetic/model/cape/",
    "mount":    "https://app.zeqa.net/cosmetic/model/mount/",
    "artifact": "https://app.zeqa.net/cosmetic/model/artifact/",
}

EXTRACTED_DIR = Path("extracted_pngs")
FLIPPED_DIR = Path("flipped_pngs")
OUTPUT_DIR = Path("output")        # final assets committed to repo
DOWNLOAD_DIR = OUTPUT_DIR / "gltfs"  # GLTFs saved here so they're committed too
# =====================================

TODAY = date.today().isoformat()      # e.g. "2025-04-30"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def file_md5(path: Path) -> str:
    """Return MD5 hex digest of a file's contents."""
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def safe_filename(name: str) -> str:
    """Strip characters that are illegal in filenames."""
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def load_cosmetics(json_path: Path) -> dict:
    if not json_path.exists():
        print(f"❌ {json_path} not found. Please commit it to the repo.")
        sys.exit(1)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("capes", "mounts", "artifacts"):
        data.setdefault(key, [])
    print(f"✅ Loaded {len(data['capes'])} capes, "
          f"{len(data['mounts'])} mounts, "
          f"{len(data['artifacts'])} artifacts.")
    return data


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_gltf(asset_type: str, asset_id: str, asset_name: str) -> Path | None:
    url_file = f"{asset_id}.gltf"                              # ID-based URL
    # {name} {id}.gltf
    out_name = f"{safe_filename(asset_name)} {asset_id}.gltf"
    dest_dir = DOWNLOAD_DIR / asset_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / out_name

    url = BASE_URLS[asset_type] + url_file
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(
                f"❌ Skipped {asset_type}/{url_file} (HTTP {resp.status_code})")
            return None
    except Exception as exc:
        print(f"⚠️  Error downloading {asset_type}/{url_file}: {exc}")
        return None

    new_bytes = resp.content

    if dest_path.exists():
        existing_md5 = hashlib.md5(dest_path.read_bytes()).hexdigest()
        new_md5 = hashlib.md5(new_bytes).hexdigest()
        if existing_md5 == new_md5:
            print(f"⏩ Unchanged: {out_name}")
            return dest_path

        # GLTF has changed — archive the old one with today's date
        archive_stem = f"{dest_path.stem}_{TODAY}"
        archive_path = dest_dir / f"{archive_stem}.gltf"
        counter = 1
        while archive_path.exists():
            archive_path = dest_dir / f"{archive_stem}_{counter}.gltf"
            counter += 1
        shutil.move(str(dest_path), archive_path)
        print(f"  📦 Archived old GLTF → {archive_path.name}")

    dest_path.write_bytes(new_bytes)
    print(f"✅ Saved {asset_type}/{out_name}")
    return dest_path


def download_all(cosmetics: dict):
    for entry in cosmetics["capes"]:
        download_gltf("cape", str(entry["id"]), entry.get("name", entry["id"]))
    for entry in cosmetics["mounts"]:
        download_gltf("mount", str(entry["id"]),
                      entry.get("name", entry["id"]))
    for entry in cosmetics["artifacts"]:
        download_gltf("artifact", str(
            entry["id"]), entry.get("name", entry["id"]))


# ---------------------------------------------------------------------------
# Extract PNGs from GLTFs
# ---------------------------------------------------------------------------

def extract_pngs_from_gltf(gltf_path: Path, output_root: Path):
    try:
        with open(gltf_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"⚠️  Invalid JSON in {gltf_path.name}: {exc}")
        return

    # stem is now "Black Butterfly C74" — extract just the ID (last token)
    asset_id = gltf_path.stem.rsplit(" ", 1)[-1]  # e.g. "C74"
    asset_type = gltf_path.parent.name               # e.g. "cape"
    out_dir = output_root / asset_type / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)

    images = data.get("images", [])
    if not images:
        print(f"  ℹ️  No images in {gltf_path.name}")
        return

    for i, img in enumerate(images):
        uri = img.get("uri", "")
        if uri.startswith("data:image/png;base64,"):
            img_bytes = base64.b64decode(uri.split(",", 1)[1])
            out_path = out_dir / f"{asset_id}_image_{i}.png"
            out_path.write_bytes(img_bytes)
            print(f"  🖼️  Extracted embedded PNG → {out_path}")
        elif uri:
            src = (gltf_path.parent / uri).resolve()
            if src.exists() and src.suffix.lower() == ".png":
                out_path = out_dir / src.name
                shutil.copy2(src, out_path)
                print(f"  🖼️  Copied linked PNG → {out_path}")


def extract_all():
    for gltf_path in sorted(DOWNLOAD_DIR.rglob("*.gltf")):
        extract_pngs_from_gltf(gltf_path, EXTRACTED_DIR)


# ---------------------------------------------------------------------------
# Flip PNGs — only entries with "flip": true in cosmetics.json
# ---------------------------------------------------------------------------

def build_flip_set(cosmetics: dict) -> set:
    """Return a set of (asset_type, str_id) that should be flipped vertically."""
    flip_set = set()
    for asset_type in ("cape", "mount", "artifact"):
        plural = asset_type + "s"
        for entry in cosmetics.get(plural, []):
            if entry.get("flip", False):
                flip_set.add((asset_type, str(entry["id"])))
    return flip_set


def flip_and_copy(input_root: Path, output_root: Path, flip_set: set):
    for png_path in sorted(input_root.rglob("*.png")):
        try:
            parts = png_path.relative_to(input_root).parts
            asset_type = parts[0]
            asset_id = parts[1]
        except (ValueError, IndexError):
            asset_type = "unknown"
            asset_id = "unknown"

        should_flip = (asset_type, asset_id) in flip_set

        try:
            img = Image.open(png_path)
            if should_flip:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
                print(f"🔄 Flipped {png_path.relative_to(input_root)}")
            else:
                print(f"⏩ No flip for {png_path.relative_to(input_root)}")

            rel = png_path.relative_to(input_root)
            save_path = output_root / rel
            save_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(save_path)
        except Exception as exc:
            print(f"⚠️  Error processing {png_path}: {exc}")


def flip_all(cosmetics: dict):
    flip_set = build_flip_set(cosmetics)
    print(f"  ℹ️  {len(flip_set)} asset(s) flagged for vertical flip.")
    flip_and_copy(EXTRACTED_DIR, FLIPPED_DIR, flip_set)


# ---------------------------------------------------------------------------
# Rename + archive changed textures
# ---------------------------------------------------------------------------

def build_id_name_map(cosmetics: dict) -> dict:
    """Return {(asset_type, str_id): safe_name}."""
    mapping = {}
    for asset_type in ("cape", "mount", "artifact"):
        plural = asset_type + "s"
        for entry in cosmetics.get(plural, []):
            raw_id = str(entry["id"])
            raw_name = entry.get("name", raw_id)
            mapping[(asset_type, raw_id)] = safe_filename(raw_name)
    return mapping


def commit_png(src: Path, dest: Path):
    """
    Copy src to dest.

    If dest already exists and the content has CHANGED:
      → Archive the old file as  <stem>_YYYY-MM-DD.png  (collision-safe)
      → Then write the new file to dest

    If dest exists and content is IDENTICAL:
      → Skip (no commit needed)

    If dest does not exist:
      → Write fresh
    """
    if dest.exists():
        if file_md5(src) == file_md5(dest):
            print(f"  ✔️  Unchanged: {dest.name}")
            return

        # Texture changed — archive the current version with today's date
        archive_stem = f"{dest.stem}_{TODAY}"
        archive_path = dest.parent / f"{archive_stem}.png"
        counter = 1
        while archive_path.exists():
            archive_path = dest.parent / f"{archive_stem}_{counter}.png"
            counter += 1

        shutil.move(str(dest), archive_path)
        print(f"  📦 Archived old texture → {archive_path.name}")

    shutil.copy2(src, dest)
    print(f"  ✅ Saved → {dest.name}")


def rename_all(cosmetics: dict):
    id_name_map = build_id_name_map(cosmetics)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    processed = 0
    for png_path in sorted(FLIPPED_DIR.rglob("*.png")):
        try:
            parts = png_path.relative_to(FLIPPED_DIR).parts
            asset_type = parts[0]   # "cape" / "mount" / "artifact"
            asset_id = parts[1]   # "C74" / "1" / "PC3" etc.
        except (ValueError, IndexError):
            print(f"⚠️  Unexpected path structure: {png_path}")
            continue

        safe_name = id_name_map.get((asset_type, asset_id))
        if not safe_name:
            print(f"⚠️  No name for {asset_type}/{asset_id}, skipping.")
            continue

        # output/capes/  output/mounts/  output/artifacts/
        out_subdir = OUTPUT_DIR / (asset_type + "s")
        out_subdir.mkdir(parents=True, exist_ok=True)

        dest = out_subdir / f"{safe_name} {asset_id}.png"
        commit_png(png_path, dest)
        processed += 1

    print(f"\n🎉 Processed {processed} files → {OUTPUT_DIR}/")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cosmetics = load_cosmetics(DATA_JSON)

    print("\n⬇️  Downloading GLTFs...")
    download_all(cosmetics)

    print("\n🧩 Extracting PNGs...")
    extract_all()

    print("\n🔄 Flipping PNGs (per-entry flag)...")
    flip_all(cosmetics)

    print("\n✏️  Renaming + archiving changed textures...")
    rename_all(cosmetics)

    print("\n✅ Pipeline complete.")
