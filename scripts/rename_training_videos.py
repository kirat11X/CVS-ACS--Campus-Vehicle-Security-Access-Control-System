"""
Renames the videos in TRAINING_VIDEOS to a plain sequence: 1.mp4, 2.mp4, 3.mp4, ...

    python3 scripts/rename_training_videos.py --dry-run      # preview only
    python3 scripts/rename_training_videos.py                # rename
    python3 scripts/rename_training_videos.py --undo         # restore the original names

Files are numbered in natural filename order (so 9_x.mp4 comes before 10_x.mp4). The original
name of every file is recorded in TRAINING_VIDEOS/rename_map.json so the rename can be undone
and the numbered clips can be traced back to their source. Running the script again after new
videos are added numbers only the new ones, after the existing sequence.
"""
import argparse
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DIR = os.path.join(PROJECT_ROOT, "TRAINING_VIDEOS")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
MAP_NAME = "rename_map.json"


def natural_key(name):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def is_sequence_name(name):
    stem, ext = os.path.splitext(name)
    return stem.isdigit() and not stem.startswith("0") and ext.lower() in VIDEO_EXTENSIONS


def load_map(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_map(path, mapping):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mapping, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def apply_renames(directory, renames):
    """Renames (old, new) pairs via unique temp names so no step can overwrite another file."""
    temps = []
    for i, (old, new) in enumerate(renames):
        temp = f".rename_tmp_{i}"
        os.rename(os.path.join(directory, old), os.path.join(directory, temp))
        temps.append((temp, new))
    for temp, new in temps:
        os.rename(os.path.join(directory, temp), os.path.join(directory, new))


def plan_forward(directory):
    videos = [
        n for n in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, n)) and os.path.splitext(n)[1].lower() in VIDEO_EXTENSIONS
    ]
    # Files already numbered by an earlier run keep their number; everything else gets the next free ones.
    taken = {int(os.path.splitext(n)[0]) for n in videos if is_sequence_name(n)}
    todo = sorted((n for n in videos if not is_sequence_name(n)), key=natural_key)
    next_number = max(taken, default=0) + 1

    renames = []
    for name in todo:
        new = f"{next_number}{os.path.splitext(name)[1].lower()}"
        renames.append((name, new))
        next_number += 1
    return renames


def plan_undo(directory, mapping):
    renames = []
    for new, original in mapping.items():
        if os.path.exists(os.path.join(directory, new)):
            renames.append((new, original))
    return renames


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=DEFAULT_DIR, help="Folder holding the videos (default: TRAINING_VIDEOS)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without renaming anything")
    parser.add_argument("--undo", action="store_true", help=f"Restore the original names from {MAP_NAME}")
    args = parser.parse_args()

    directory = os.path.abspath(args.dir)
    if not os.path.isdir(directory):
        sys.exit(f"Not a directory: {directory}")
    map_path = os.path.join(directory, MAP_NAME)
    mapping = load_map(map_path)

    if args.undo:
        if not mapping:
            sys.exit(f"Nothing to undo: {map_path} is missing or empty.")
        renames = plan_undo(directory, mapping)
        clashes = [orig for _, orig in renames if os.path.exists(os.path.join(directory, orig))]
        if clashes:
            sys.exit(f"Refusing to overwrite existing files: {', '.join(clashes[:5])}")
    else:
        renames = plan_forward(directory)

    if not renames:
        print("Nothing to rename.")
        return

    for old, new in renames:
        print(f"{old}  ->  {new}")
    print(f"\n{len(renames)} file(s)" + (" (dry run, nothing changed)" if args.dry_run else ""))
    if args.dry_run:
        return

    apply_renames(directory, renames)

    if args.undo:
        for new, _ in renames:
            mapping.pop(new, None)
    else:
        for old, new in renames:
            mapping[new] = old
    mapping = dict(sorted(mapping.items(), key=lambda kv: natural_key(kv[0])))
    if mapping:
        save_map(map_path, mapping)
    elif os.path.exists(map_path):
        os.remove(map_path)


if __name__ == "__main__":
    main()
