"""Build the Person C -> Person D integration fixture from one E.ROIs artifact.

    python components/person_d/examples/person_c_integration/make_fixture.py \
      --e ../run/input/person_d/integration_c/E_rois.json \
      --out-dir ../run/input/person_d/integration_c

Writes next to E:

- ``G_queries.json``: a G.VisualAttributeQueries fixture for the same case.  The case metadata
  comes from E; the single diagnostic pair reuses the queries of
  ``examples/G_queries.valid.json`` (001: real criteria, 004 / 005: synthetic acceptance queries)
  and names every stain that has ROIs as ``referenceWSI``.
- ``example-he.tiff``: a synthetic pyramidal generic tiled TIFF with tissue-like texture inside
  the ROI boxes of the first stain that has ROIs.  No patient data.

E is only read.  Needs numpy and tifffile (not runtime dependencies of the component).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from contracts.runtime import validate_artifact  # noqa: E402


EXAMPLE_G = REPO / "components/person_d/examples/G_queries.valid.json"
TILE = 512
LEVELS = (4, 16)
BACKGROUND = 245
STROMA_RGB = (232, 168, 196)
NUCLEUS_RGB = (92, 58, 150)
# (nuclei per 512 px tile, nucleus radius range in px, axis irregularity) per ROI, cycled in ROI order
TEXTURES = [(110, (7, 13), 0.45), (25, (3, 5), 0.05), (60, (5, 9), 0.25), (90, (6, 11), 0.35)]


def build_g(e: dict) -> dict:
    example = json.loads(EXAMPLE_G.read_text(encoding="utf-8"))
    example_case = example["payload"]["case_list"][0]
    case = copy.deepcopy(e["payload"]["case_list"][0])
    case_id = case["case_id"]
    reference = []
    for block in case["tissue_blocks"]:
        for stain in block["stains"]:
            if stain["roi_list"]:
                reference.append(stain["stain_id"])
            stain["roi_num"], stain["roi_list"] = 0, []

    record = copy.deepcopy(example_case["structured_report"]["DxItems"]["Histologic_Type"])
    record["dx_pair_id"] = f"{case_id}-dx-001"
    record["referenceWSI"] = reference
    for query in record["visualAttrQueries"]:
        query["query_id"] = query["query_id"].replace("case-001", case_id)
        query["dx_pair_id"] = record["dx_pair_id"]
    report = copy.deepcopy(example_case["structured_report"])
    report["DxItems"] = {e["payload"]["DxItem_list"][0]: record}
    case["structured_report"] = report

    g = {
        "contract": "G.VisualAttributeQueries",
        "schema_version": "2.0",
        "artifact_id": f"G-{case_id}",
        "case_id": case_id,
        "producer": "person-d/integration-fixture",
        "payload": {
            "data_mode": e["payload"]["data_mode"],
            "DxItem_list": list(e["payload"]["DxItem_list"]),
            "reference_versions": copy.deepcopy(example["payload"]["reference_versions"]),
            "case_list": [case],
        },
    }
    validate_artifact(g, "G.VisualAttributeQueries")
    return g


def roi_boxes(e: dict) -> list[list[int]]:
    for block in e["payload"]["case_list"][0]["tissue_blocks"]:
        for stain in block["stains"]:
            if stain["roi_list"]:
                return [list(roi["level0_info"]["xywh"]) for roi in stain["roi_list"]]
    raise ValueError("E has no ROI")


def write_slide(path: Path, boxes: list[list[int]], width: int, height: int, mpp: float) -> str:
    """Write the slide and return the SHA-256 of its level-0 RGB pixels in row-major order."""

    import numpy as np
    import tifffile

    regions = [(*box, *TEXTURES[index % len(TEXTURES)]) for index, box in enumerate(boxes)]
    cols, rows = -(-width // TILE), -(-height // TILE)
    pyramid = {
        factor: np.full((-(-height // factor), -(-width // factor), 3), BACKGROUND, np.uint8)
        for factor in LEVELS
    }
    pixels = hashlib.sha256()

    def texture(tx: int, ty: int, density: int, radius: tuple[int, int], irregular: float, seed: int):
        rng = np.random.default_rng((tx * 100003 + ty) * 31 + seed)
        yy, xx = np.mgrid[0:TILE, 0:TILE].astype(np.float32)
        coarse = rng.normal(0, 8, (TILE // 32, TILE // 32, 1)).astype(np.float32)
        tissue = np.array(STROMA_RGB, np.float32) + np.repeat(np.repeat(coarse, 32, 0), 32, 1)
        mask = np.zeros((TILE, TILE), bool)
        for _ in range(density):
            cx, cy = rng.uniform(0, TILE, 2)
            r = rng.uniform(*radius)
            ax, ay = (r * (1 + irregular * rng.uniform(-1, 1)) for _ in range(2))
            mask |= ((xx - cx) / ax) ** 2 + ((yy - cy) / ay) ** 2 <= 1
        tissue[mask] = NUCLEUS_RGB
        return np.clip(tissue, 0, 255).astype(np.uint8)

    def tiles():
        for ty in range(rows):
            row = []
            for tx in range(cols):
                x0, y0 = tx * TILE, ty * TILE
                tile = np.full((TILE, TILE, 3), BACKGROUND, np.uint8)
                for seed, (x, y, w, h, density, radius, irregular) in enumerate(regions):
                    ix0, iy0 = max(x, x0), max(y, y0)
                    ix1, iy1 = min(x + w, x0 + TILE), min(y + h, y0 + TILE)
                    if ix0 < ix1 and iy0 < iy1:
                        patch = texture(tx, ty, density, radius, irregular, seed)
                        tile[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = patch[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0]
                for factor, level in pyramid.items():
                    small = tile.reshape(TILE // factor, factor, TILE // factor, factor, 3).mean((1, 3)).astype(np.uint8)
                    ly, lx = y0 // factor, x0 // factor
                    h_ = min(small.shape[0], level.shape[0] - ly)
                    w_ = min(small.shape[1], level.shape[1] - lx)
                    level[ly:ly + h_, lx:lx + w_] = small[:h_, :w_]
                row.append(tile)
                yield tile
            strip = np.concatenate(row, axis=1)[: min(TILE, height - ty * TILE), :width]
            pixels.update(np.ascontiguousarray(strip).tobytes())

    options = dict(photometric="rgb", compression="zlib", resolutionunit="CENTIMETER")
    with tifffile.TiffWriter(path, bigtiff=True) as tif:
        tif.write(tiles(), shape=(height, width, 3), dtype=np.uint8, tile=(TILE, TILE),
                  resolution=(1e4 / mpp, 1e4 / mpp), **options)
        for factor, level in pyramid.items():
            # OpenSlide 4 only takes directories marked reduced-resolution as pyramid levels.
            tif.write(level, tile=(256, 256), subfiletype=1,
                      resolution=(1e4 / (mpp * factor), 1e4 / (mpp * factor)), **options)
    return pixels.hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="丁: Person C -> Person D integration fixture")
    parser.add_argument("--e", required=True, help="E.ROIs artifact produced by Person C")
    parser.add_argument("--out-dir", required=True, help="Directory for G_queries.json and example-he.tiff")
    parser.add_argument("--width", type=int, default=30000, help="Slide width in level-0 px")
    parser.add_argument("--height", type=int, default=20000, help="Slide height in level-0 px")
    parser.add_argument("--mpp", type=float, default=0.25, help="Level-0 microns per pixel")
    args = parser.parse_args()

    e = json.loads(Path(args.e).read_text(encoding="utf-8"))
    validate_artifact(e, "E.ROIs")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    g_path = out / "G_queries.json"
    g_path.write_text(json.dumps(build_g(e), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    slide_path = out / "example-he.tiff"
    boxes = roi_boxes(e)
    pixel_digest = write_slide(slide_path, boxes, args.width, args.height, args.mpp)

    print(f"G        {g_path} sha256 {file_sha256(g_path)}")
    print(f"slide    {slide_path} {args.width} x {args.height} px, mpp {args.mpp}, levels 1/{'/'.join(map(str, LEVELS))}")
    print(f"         ROI boxes {boxes}")
    print(f"         level-0 pixel sha256 {pixel_digest}")
    print(f"         file sha256 {file_sha256(slide_path)}")


if __name__ == "__main__":
    main()
