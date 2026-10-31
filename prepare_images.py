#!/usr/bin/env python3
"""Turn downloaded balloon photos into web-sized images named after each balloon's id.

Put the original photos (from Google Photos "Download all") in photos-original/,
then run:

    python3 prepare_images.py                  # uses register.csv
    python3 prepare_images.py --csv sheet.csv  # or a fresh export of the sheet

For every row in the register:
  * .img = "n/a"          -> no photo, skipped
  * .img = "IMG_4521.jpg" -> photos-original/IMG_4521.jpg becomes images/details/<id>.jpg
  * .img = "IMG_4521.jpg, IMG_4530.HEIC, ..."
                          -> several photos for the details page carousel; the first
                             is the cover (images/details/<id>.jpg), then <id>-2.jpg, -3, ...
  * .img empty            -> files in photos-original/ named after the id: ly-auz.jpg
                             (cover), ly-auz-2.jpg, ly-auz-3.jpg, ... (any case/extension)

Each cover also gets a 10:7 centre-cropped copy for the list page's cards, in
images/cards/<id>.jpg. Prefer your own crop? Save it over that file: a card is only
remade when its cover is newer, or with --force.

Finally index.json (next to index.html) is written with the total number of photos
in images/details/ and the number of photos per id, which the
details page uses to build its carousel. Extra <id>-N.jpg files left over from an
earlier run with more photos are removed.

Added photos to images/details/ by hand? Run with --index-only to just make their cards and
rebuild index.json from the files in images/details/ (no originals needed). The site only
shows photos listed there.

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
CARD_WIDTH, CARD_HEIGHT = 680, 476  # 10:7, sharp on the widest cards (339px on phones) at 2x


def image_size(path):
    out = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    width, height = [int(line.split(":")[1]) for line in out.splitlines() if "pixel" in line]
    return width, height


def convert(src, dst, size, quality):
    cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality)]
    if max(image_size(src)) > size:
        cmd += ["-Z", str(size)]
    cmd += [str(src), "--out", str(dst)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def is_cover(stem, names):
    """<id>-N is a carousel photo only if <id> exists, as some ids end in a number (ly-oae-1)."""
    m = re.search(r"-\d+$", stem)
    return not (m and stem[:m.start()] in names)


def make_card(src, dst, quality):
    """Save a centre crop of src at the card's aspect ratio, shrunk (never enlarged) to card size."""
    width, height = image_size(src)
    crop_width = min(width, round(height * CARD_WIDTH / CARD_HEIGHT))
    crop_height = min(height, round(width * CARD_HEIGHT / CARD_WIDTH))
    subprocess.run(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality),
         "--cropToHeightWidth", str(crop_height), str(crop_width), str(src), "--out", str(dst)],
        capture_output=True, text=True, check=True,
    )
    if crop_width > CARD_WIDTH:
        subprocess.run(
            ["sips", "-s", "formatOptions", str(quality),
             "-z", str(CARD_HEIGHT), str(CARD_WIDTH), str(dst)],
            capture_output=True, text=True, check=True,
        )


def make_cards(details, cards, quality, force):
    """Make cards/<id>.jpg for each cover in details/, keep newer ones (they may be hand-made), drop orphans. Returns (made, failed)."""
    cards.mkdir(exist_ok=True)
    names = {p.stem for p in details.glob("*.jpg")}
    covers = {p.stem: p for p in details.glob("*.jpg") if is_cover(p.stem, names)}
    made, failed = 0, []
    for stem, cover in sorted(covers.items()):
        dst = cards / f"{stem}.jpg"
        if dst.exists() and dst.stat().st_mtime >= cover.stat().st_mtime and not force:
            continue
        try:
            make_card(cover, dst, quality)
            made += 1
            print(f"  {cover.name} -> {cards.name}/{dst.name}")
        except subprocess.CalledProcessError as err:
            failed.append(f"{stem}: card ({err.stderr.strip() or err})")
    for stale in cards.glob("*.jpg"):
        if stale.stem not in covers:
            stale.unlink()
            print(f"  removed {cards.name}/{stale.name}")
    return made, failed


def write_index(details, path):
    """Write index.json at path: "total" photos in details/, then photo count per id from its <id>.jpg / <id>-N.jpg files."""
    names = {p.stem for p in details.glob("*.jpg")}
    index = {}
    for stem in names:
        if not is_cover(stem, names):
            continue  # a carousel photo; counted with its cover below
        count = 1
        while f"{stem}-{count + 1}" in names:
            count += 1
        index[stem] = count
    data = {"total": len(names), **dict(sorted(index.items()))}
    path.write_text(json.dumps(data, indent=0, ensure_ascii=False) + "\n")
    return index, len(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=HERE / "register.csv", help="register CSV (default: register.csv)")
    parser.add_argument("--originals", type=Path, default=HERE / "photos-original", help="folder with downloaded photos")
    parser.add_argument("--out", type=Path, default=HERE / "images", help="output folder, holding details/ and cards/ (default: images)")
    parser.add_argument("--size", type=int, default=1200, help="longest side in pixels (default: 1200)")
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100 (default: 80)")
    parser.add_argument("--force", action="store_true", help="redo images that already exist")
    parser.add_argument("--index", type=Path, default=HERE / "index.json", help="photo index file (default: index.json next to the site)")
    parser.add_argument("--index-only", action="store_true", help="only make cards and rebuild index.json from the files in images/details/")
    args = parser.parse_args()
    details = args.out / "details"
    cards = args.out / "cards"

    if args.index_only:
        if not details.is_dir():
            sys.exit(f"No photos folder at {details}.")
        made, card_failed = make_cards(details, cards, args.quality, args.force)
        index, total = write_index(details, args.index)
        multi = sum(1 for c in index.values() if c > 1)
        print(f"{total} photos in {details.name}/; {len(index)} balloons have photos ({multi} with more than one); {made} cards made; wrote {args.index.name}.")
        if card_failed:
            print("\n".join(f"  {f}" for f in card_failed))
            sys.exit(1)
        return

    if not args.originals.is_dir():
        sys.exit(f"No originals folder at {args.originals}. Put the downloaded photos there first.")
    details.mkdir(parents=True, exist_ok=True)

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
            dst = details / (f"{balloon_id}.jpg" if n == 1 else f"{balloon_id}-{n}.jpg")
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
        for stale in details.glob(f"{balloon_id}-*.jpg"):
            m = re.fullmatch(rf"{re.escape(balloon_id)}-(\d+)", stale.stem)
            if m and int(m.group(1)) > len(sources):
                stale.unlink()
                made_from.pop(stale.name, None)
                print(f"  removed {stale.name}")

    cards_made, card_failed = make_cards(details, cards, args.quality, args.force)
    failed += card_failed
    index, total = write_index(details, args.index)
    multi = sum(1 for c in index.values() if c > 1)
    made_from_file.write_text(json.dumps(made_from, indent=0, sort_keys=True) + "\n")

    unused = sorted(p.name for p in originals if p not in used)

    print(f"\nConverted {done}, already up to date {skipped}, marked n/a {no_photo}.")
    print(f"{total} photos in {details.name}/; {len(index)} balloons have photos ({multi} with more than one); {cards_made} cards made; wrote {args.index.name}.")
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
