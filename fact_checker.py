"""
merge_cosmetics.py
------------------
Fetches https://inpvp.net/api/zeqa-cosmetics?gamertag=chainmail,
then adds any capes / mounts / artifacts that are missing from
cluster.json.  New entries get "flip": false by default.

Usage:
    python merge_cosmetics.py                    # reads/writes cluster.json in cwd
    python merge_cosmetics.py path/to/cluster.json
"""

import json
import sys
import requests
from pathlib import Path

# ── config ───────────────────────────────────────────────────────────────────
API_URL = "https://inpvp.net/api/zeqa-cosmetics?gamertag=chainmail"
JSON_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cluster.json")

# Map API type names → keys used in cluster.json
TYPE_TO_KEY = {
    "cape":     "capes",
    "mount":    "mounts",
    "artifact": "artifacts",
}
# ─────────────────────────────────────────────────────────────────────────────


def load_cluster(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("capes", "mounts", "artifacts"):
        data.setdefault(key, [])
    return data


def fetch_api(url: str) -> dict:
    print(f"Fetching {url} …")
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("found"):
        raise ValueError(f"API returned found=false: {data}")
    return data


def build_existing_ids(cluster: dict, key: str) -> set:
    return {str(entry["id"]) for entry in cluster.get(key, [])}


def merge(cluster: dict, api_data: dict) -> tuple[dict, int]:
    added = 0
    for type_block in api_data.get("types", []):
        asset_type = type_block.get("type")
        cluster_key = TYPE_TO_KEY.get(asset_type)
        if cluster_key is None:
            continue  # skip killphrases, projectiles, etc.

        existing_ids = build_existing_ids(cluster, cluster_key)

        for item in type_block.get("items", []):
            item_id = str(item["id"])
            if item_id in existing_ids:
                continue  # already present

            new_entry = {
                "id":   item_id,
                "name": item.get("name", item_id),
                "flip": False,
            }
            cluster[cluster_key].append(new_entry)
            existing_ids.add(item_id)
            added += 1
            print(f"  ➕ Added {asset_type} {item_id!r} ({new_entry['name']!r})")

    return cluster, added


def save_cluster(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved → {path}")


def main():
    if not JSON_PATH.exists():
        print(f"❌ {JSON_PATH} not found.")
        sys.exit(1)

    cluster = load_cluster(JSON_PATH)
    api_data = fetch_api(API_URL)
    cluster, added = merge(cluster, api_data)

    if added == 0:
        print("\nℹ️  Nothing to add — cluster.json is already up to date.")
    else:
        save_cluster(JSON_PATH, cluster)
        print(f"🎉 Added {added} new entries to {JSON_PATH}")


if __name__ == "__main__":
    main()
