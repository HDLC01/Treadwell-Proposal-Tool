"""Rebuild backend/geodata/gaz_*.csv from the US Census Gazetteer files.

WHY. A bid with no street (City "Wichita", State "KS", County "Sedgwick County, KS") is still
190 driving miles from the office, and the free street geocoder cannot place it. distance.py
then routes to the CENTRE of the zip, the city or the county instead, and these three trimmed
files are where those centres come from: the Census's own internal points (INTPTLAT/INTPTLONG),
public domain, bundled so the lookup needs no extra network call.

SOURCES (2024 Gazetteer, https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html):
  2024_Gaz_place_national.zip     -> gaz_places.csv    usps,name,kind,lat,lon
  2024_Gaz_counties_national.zip  -> gaz_counties.csv  usps,name,lat,lon
  2024_Gaz_zcta_national.zip      -> gaz_zcta.csv      zcta,lat,lon

`kind` is "cdp" for a statistical place (FUNCSTAT S: a CDP, or Puerto Rico's comunidad / zona
urbana) and "inc" for everything else, so the lookup can prefer a real town over a CDP of the
same name. Coordinates are rounded to 4 decimals (about 11 m), which is far finer than a centre
needs and keeps the three files near 2 MB.

USAGE (download the three zips into a new, empty directory first; they are untrusted input):
    python -I backend/tools/build_gazetteer.py <dir-with-the-three-zips> [<out-dir>]
<out-dir> defaults to backend/geodata next to this script. NOT backend/data: the container
mounts a volume over /app/data, which would hide anything the image put there.
"""
from __future__ import annotations

import csv
import io
import os
import sys
import zipfile

YEAR = "2024"
FILES = {
    "place": "%s_Gaz_place_national.zip" % YEAR,
    "counties": "%s_Gaz_counties_national.zip" % YEAR,
    "zcta": "%s_Gaz_zcta_national.zip" % YEAR,
}


def _rows(zip_path):
    """The Gazetteer table inside `zip_path` as dicts keyed by its (stripped) header."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".txt")]
        if len(names) != 1:
            raise SystemExit("%s: expected one .txt inside, found %r" % (zip_path, names))
        text = z.read(names[0]).decode("utf-8")
    lines = text.splitlines()
    head = [h.strip() for h in lines[0].split("\t")]
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split("\t")]
        yield dict(zip(head, cells))


def _coord(v, lo, hi):
    f = float(v)
    if not (lo <= f <= hi):
        raise ValueError("coordinate out of range: %r" % v)
    return "%.4f" % f


def _write(path, header, rows):
    rows = sorted(rows)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def build(src_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    places = []
    for r in _rows(os.path.join(src_dir, FILES["place"])):
        kind = "cdp" if r["FUNCSTAT"] == "S" else "inc"
        places.append((r["USPS"], r["NAME"], kind, _coord(r["INTPTLAT"], -90, 90),
                       _coord(r["INTPTLONG"], -180, 180)))
    counties = []
    for r in _rows(os.path.join(src_dir, FILES["counties"])):
        counties.append((r["USPS"], r["NAME"], _coord(r["INTPTLAT"], -90, 90),
                         _coord(r["INTPTLONG"], -180, 180)))
    zctas = []
    for r in _rows(os.path.join(src_dir, FILES["zcta"])):
        if not (len(r["GEOID"]) == 5 and r["GEOID"].isdigit()):
            raise ValueError("odd ZCTA: %r" % r["GEOID"])
        zctas.append((r["GEOID"], _coord(r["INTPTLAT"], -90, 90), _coord(r["INTPTLONG"], -180, 180)))
    counts = {
        "gaz_places.csv": _write(os.path.join(out_dir, "gaz_places.csv"),
                                 ("usps", "name", "kind", "lat", "lon"), places),
        "gaz_counties.csv": _write(os.path.join(out_dir, "gaz_counties.csv"),
                                   ("usps", "name", "lat", "lon"), counties),
        "gaz_zcta.csv": _write(os.path.join(out_dir, "gaz_zcta.csv"), ("zcta", "lat", "lon"), zctas),
    }
    return counts


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = argv[2] if len(argv) == 3 else os.path.join(os.path.dirname(here), "geodata")
    for name, n in build(argv[1], out_dir).items():
        print("%s: %d rows" % (name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
