#!/usr/bin/env python3
"""Turn downloaded balloon photos into web-sized images named after each balloon's id.

Put the original photos (from Google Photos "Download all") in photos-original/,
then run:

    python3 prepare_images.py                  # uses register.csv
    python3 prepare_images.py --csv sheet.csv  # or a fresh export of the sheet

For every row in the register:
  * .img = "n/a"          -> no photo, skipped
  * .img = "IMG_4521.jpg" -> photos-original/IMG_4521.jpg becomes images/<id>.jpg
  * .img empty            -> a file in photos-original/ named after the id
                             (ly-auz.jpg, LY-AUZ.HEIC, ...) becomes images/<id>.jpg

Images are shrunk so the longest side is at most --size pixels (never enlarged)
and saved as JPEG. Uses macOS's built-in `sips`, so HEIC photos work too.
Already-converted photos are skipped unless the original is newer or --force is given.
"""

import argparse
import csv
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=HERE / "register.csv", help="register CSV (default: register.csv)")
    parser.add_argument("--originals", type=Path, default=HERE / "photos-original", help="folder with downloaded photos")
    parser.add_argument("--out", type=Path, default=HERE / "images", help="output folder (default: images)")
    parser.add_argument("--size", type=int, default=1200, help="longest side in pixels (default: 1200)")
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100 (default: 80)")
    parser.add_argument("--force", action="store_true", help="redo images that already exist")
    args = parser.parse_args()

    if not args.originals.is_dir():
        sys.exit(f"No originals folder at {args.originals}. Put the downloaded photos there first.")
    args.out.mkdir(exist_ok=True)

    # Case-insensitive lookup: by full filename and by filename without extension.
    originals = [p for p in args.originals.iterdir() if p.suffix.lower() in PHOTO_EXTS]
    by_name = {p.name.lower(): p for p in originals}
    by_stem = {p.stem.lower(): p for p in originals}

    with open(args.csv, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("id") or "").strip()]

    done, skipped, no_photo, missing, failed, used = 0, 0, 0, [], [], set()
    for row in rows:
        balloon_id = row["id"].strip()
        wanted = (row.get(".img") or "").strip()
        if wanted.lower() == "n/a":
            no_photo += 1
            continue

        if wanted:
            name = Path(wanted).name.lower()
            src = by_name.get(name) or by_stem.get(Path(name).stem)
        else:
            src = by_stem.get(balloon_id.lower())
        if not src:
            missing.append(f"{balloon_id} ({wanted or 'no .img, no file named after id'})")
            continue
        used.add(src)

        dst = args.out / f"{balloon_id}.jpg"
        if dst.exists() and not args.force and dst.stat().st_mtime >= src.stat().st_mtime:
            skipped += 1
            continue
        try:
            convert(src, dst, args.size, args.quality)
            done += 1
            print(f"  {src.name} -> {dst.relative_to(HERE) if dst.is_relative_to(HERE) else dst}")
        except subprocess.CalledProcessError as err:
            failed.append(f"{balloon_id}: {src.name} ({err.stderr.strip() or err})")

    unused = sorted(p.name for p in originals if p not in used)

    print(f"\nConverted {done}, already up to date {skipped}, marked n/a {no_photo}.")
    if missing:
        print(f"\nNo photo found for {len(missing)} balloons:")
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
