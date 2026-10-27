#!/usr/bin/env python3
"""Turn downloaded balloon photos into web-sized images named after each balloon's id.

Put the original photos (from Google Photos "Download all") in photos-original/,
then run:

    python3 prepare_images.py                  # uses register.csv
    python3 prepare_images.py --csv sheet.csv  # or a fresh export of the sheet

For every row in the register:
  * .img = "n/a"          -> no photo, skipped
  * .img = "IMG_4521.jpg" -> photos-original/IMG_4521.jpg becomes images/<id>.jpg
  * .img = "IMG_4521.jpg, IMG_4530.HEIC, ..."
                          -> several photos for the details page carousel; the first
                             is the cover (images/<id>.jpg), then images/<id>-2.jpg, -3, ...
  * .img empty            -> files in photos-original/ named after the id: ly-auz.jpg
                             (cover), ly-auz-2.jpg, ly-auz-3.jpg, ... (any case/extension)

Finally images/index.json is written with the number of photos per id, which the
details page uses to build its carousel. Extra <id>-N.jpg files left over from an
earlier run with more photos are removed.

Added photos to images/ by hand? Run with --index-only to just rebuild index.json
from the files in images/ (no originals needed). The site only shows photos listed there.

Images are shrunk so the longest side is at most --size pixels (never enlarged)
and saved as JPEG. Uses macOS's built-in `sips`, so HEIC photos work too.
Already-converted photos are skipped unless the original is newer or --force is given.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}


def image_size(path):
    out = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    values = [int(line.split(":")[1]) for line in out.splitlines() if "pixel" in line]
    return max(values) if values else 0


def convert(src, dst, size, quality):
    cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality)]
    if image_size(src) > size:
        cmd += ["-Z", str(size)]
    cmd += [str(src), "--out", str(dst)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def write_index(out):
    """Write out/index.json: photo count per id, from the <id>.jpg / <id>-N.jpg files in out/."""
    names = {p.stem for p in out.glob("*.jpg")}
    index = {}
    for stem in names:
        if re.search(r"-\d+$", stem):
            continue  # a carousel photo; counted with its cover below
        count = 1
        while f"{stem}-{count + 1}" in names:
            count += 1
        index[stem] = count
    (out / "index.json").write_text(json.dumps(index, indent=0, sort_keys=True) + "\n")
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=HERE / "register.csv", help="register CSV (default: register.csv)")
    parser.add_argument("--originals", type=Path, default=HERE / "photos-original", help="folder with downloaded photos")
    parser.add_argument("--out", type=Path, default=HERE / "images", help="output folder (default: images)")
    parser.add_argument("--size", type=int, default=1200, help="longest side in pixels (default: 1200)")
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100 (default: 80)")
    parser.add_argument("--force", action="store_true", help="redo images that already exist")
    parser.add_argument("--index-only", action="store_true", help="only rebuild images/index.json from the files in images/")
    args = parser.parse_args()

    if args.index_only:
        if not args.out.is_dir():
            sys.exit(f"No images folder at {args.out}.")
        index = write_index(args.out)
        multi = sum(1 for c in index.values() if c > 1)
        print(f"{len(index)} balloons have photos ({multi} with more than one); wrote {args.out.name}/index.json.")
        return

    if not args.originals.is_dir():
        sys.exit(f"No originals folder at {args.originals}. Put the downloaded photos there first.")
    args.out.mkdir(exist_ok=True)

    # Case-insensitive lookup: by full filename and by filename without extension.
    originals = [p for p in args.originals.iterdir() if p.suffix.lower() in PHOTO_EXTS]
    by_name = {p.name.lower(): p for p in originals}
    by_stem = {p.stem.lower(): p for p in originals}

    with open(args.csv, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("id") or "").strip()]

    def numbered(balloon_id):
        """Originals named <id>-2, <id>-3, ... in number order."""
        pattern = re.compile(rf"{re.escape(balloon_id.lower())}-(\d+)")
        hits = [(int(m.group(1)), p) for p in originals if (m := pattern.fullmatch(p.stem.lower()))]
        return [p for _, p in sorted(hits, key=lambda h: h[0])]

    # Which original each output was made from, so reordering photos redoes them.
    made_from_file = args.out / ".sources.json"
    made_from = json.loads(made_from_file.read_text()) if made_from_file.exists() else {}

    done, skipped, no_photo, missing, failed, used = 0, 0, 0, [], [], set()
    for row in rows:
        balloon_id = row["id"].strip()
        wanted = (row.get(".img") or "").strip()
        if wanted.lower() == "n/a":
            no_photo += 1
            continue

        sources = []
        if wanted:
            for name in (n.strip() for n in wanted.split(",")):
                if not name:
                    continue
                name = Path(name).name.lower()
                src = by_name.get(name) or by_stem.get(Path(name).stem)
                if src:
                    sources.append(src)
                else:
                    missing.append(f"{balloon_id} ({name})")
        else:
            cover = by_stem.get(balloon_id.lower())
            sources = ([cover] if cover else []) + numbered(balloon_id)
            if not sources:
                missing.append(f"{balloon_id} (no .img, no file named after id)")
        if not sources:
            continue
        used.update(sources)

        for n, src in enumerate(sources, start=1):
            dst = args.out / (f"{balloon_id}.jpg" if n == 1 else f"{balloon_id}-{n}.jpg")
            up_to_date = dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime
            if up_to_date and made_from.get(dst.name) == src.name and not args.force:
                skipped += 1
                continue
            try:
                convert(src, dst, args.size, args.quality)
                made_from[dst.name] = src.name
                done += 1
                print(f"  {src.name} -> {dst.relative_to(HERE) if dst.is_relative_to(HERE) else dst}")
            except subprocess.CalledProcessError as err:
                failed.append(f"{balloon_id}: {src.name} ({err.stderr.strip() or err})")

        # Drop carousel photos left over from a run that had more of them.
        for stale in args.out.glob(f"{balloon_id}-*.jpg"):
            m = re.fullmatch(rf"{re.escape(balloon_id)}-(\d+)", stale.stem)
            if m and int(m.group(1)) > len(sources):
                stale.unlink()
                made_from.pop(stale.name, None)
                print(f"  removed {stale.name}")

    index = write_index(args.out)
    multi = sum(1 for c in index.values() if c > 1)
    made_from_file.write_text(json.dumps(made_from, indent=0, sort_keys=True) + "\n")

    unused = sorted(p.name for p in originals if p not in used)

    print(f"\nConverted {done}, already up to date {skipped}, marked n/a {no_photo}.")
    print(f"{len(index)} balloons have photos ({multi} with more than one); wrote {args.out.name}/index.json.")
    if missing:
        print(f"\n{len(missing)} photos not found:")
        print("\n".join(f"  {m}" for m in missing))
    if unused:
        print(f"\n{len(unused)} photos in {args.originals.name}/ aren't linked to any balloon:")
        print("\n".join(f"  {n}" for n in unused))
    if failed:
        print(f"\nFailed to convert {len(failed)}:")
        print("\n".join(f"  {f}" for f in failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
