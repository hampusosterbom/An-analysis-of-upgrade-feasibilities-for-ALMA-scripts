import re
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from pyproj import CRS, Transformer
import simplekml
import argparse

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_cfg(path: str) -> pd.DataFrame:
    """Read a .cfg file and return a DataFrame with pad positions."""
    path = str(Path(path).resolve())
    rows = []
    with open(path) as fh:
        for L in fh:
            L = L.strip()
            if not L or L.startswith('#'):  # skip comments and blank lines
                continue
            parts = re.split(r"\s+", L)
            if len(parts) == 5:
                x, y, z, diam, name = parts
            elif len(parts) == 4:
                name, x, y, z = parts
            else:
                continue
            rows.append({
                'name': name,
                'x': float(x),
                'y': float(y)
            })
    return pd.DataFrame(rows)

def generate_kml_from_cfg(
    cfg_path: str,
    kml_path: Optional[str] = None,
    *,
    lat0: float = -23.02271113,
    lon0: float = -67.75436287,
    doc_name: str = "ALMA Pads"
) -> simplekml.Kml:
    """Convert a .cfg file (local X/Y coordinates) to a KML file with ground markers."""
    df = parse_cfg(cfg_path)

    # Define local projection (AEQD) centered on lat0/lon0
    proj4 = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs"
    crs_proj = CRS.from_proj4(proj4)
    crs_wgs = CRS.from_epsg(4326)
    transformer = Transformer.from_crs(crs_proj, crs_wgs, always_xy=True)

    kml = simplekml.Kml(name=doc_name)

    # Loop through each pad and add to KML
    for _, row in df.iterrows():
        lon, lat = transformer.transform(row['x'], row['y'])
        coords = [(lon, lat)]  # no altitude
        pnt = kml.newpoint(name=str(row['name']), coords=coords)
        pnt.altitudemode = simplekml.AltitudeMode.clamptoground
        pnt.description = (
            f"x={row['x']:.3f} m\n"
            f"y={row['y']:.3f} m"
        )

    # Save to file if path provided
    if kml_path:
        kml.save(kml_path)
        logging.info(f"Saved KML to {kml_path}")

    return kml

def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Convert ALMA .cfg pads to Google Earth KML (no elevation)")
    parser.add_argument('--cfg_path', required=True, help='Path to input .cfg')
    parser.add_argument('--kml_path', required=True, help='Output .kml path')
    parser.add_argument('--lat0', type=float, default=-23.02271113, help='AEQD origin latitude')
    parser.add_argument('--lon0', type=float, default=-67.75436287, help='AEQD origin longitude')
    args = parser.parse_args()

    generate_kml_from_cfg(
        cfg_path=args.cfg_path,
        kml_path=args.kml_path,
        lat0=args.lat0,
        lon0=args.lon0
    )

if __name__ == "__main__":
    # Example
    
    generate_kml_from_cfg(r"alma.cycle11.10.cfg", "example.kml")
    print("Example KML file generated: example.kml")
