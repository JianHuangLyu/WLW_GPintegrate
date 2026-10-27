"""WSI inference and geometry for person C's MRCPS interest extractor."""

from __future__ import annotations

from hashlib import sha256
from math import ceil, floor, isfinite
from pathlib import Path
from typing import Any, Iterator

from contracts.paths import resolve_person_reference_path


def positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a positive number")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


def integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def validate_settings(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("person_c config must be a JSON object")
    version = config.get("component_version")
    if not isinstance(version, str) or not version:
        raise ValueError("person_c config requires component_version")
    # The pre-existing integration fixture has demo_regions but no backend key.
    backend = config.get("backend", "demo" if "demo_regions" in config else "mrcps")
    if backend not in {"demo", "mrcps"}:
        raise ValueError("person_c backend must be demo or mrcps")
    result = {**config, "backend": backend}
    whitelist = result.get("stain_type_whitelist")
    if (
        not isinstance(whitelist, list)
        or not whitelist
        or any(not isinstance(value, str) or not value.strip() for value in whitelist)
    ):
        raise ValueError("person_c stain_type_whitelist must be a non-empty string list")
    normalized_whitelist = [value.strip().upper() for value in whitelist]
    if len(normalized_whitelist) != len(set(normalized_whitelist)):
        raise ValueError("person_c stain_type_whitelist contains duplicates")
    result["stain_type_whitelist"] = normalized_whitelist
    if backend == "demo":
        if not isinstance(result.get("demo_regions"), list) or not isinstance(result.get("demo_mpp"), dict):
            raise ValueError("person_c demo requires demo_regions and demo_mpp")
        return result
    model = result.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("path"), str) or not model["path"]:
        raise ValueError("person_c mrcps requires model.path")
    for name in ("patch_size", "stride", "low_resolution_ratio", "batch_size", "background_dilation_kernel", "min_object_size"):
        result[name] = integer(result.get(name), name, 1)
    if result["stride"] > result["patch_size"]:
        raise ValueError("person_c stride cannot exceed patch_size")
    for name in ("check_mpp", "postprocess_mpp"):
        result[name] = positive_number(result.get(name), name)
    for name in ("background_lower", "background_upper", "hole_area_threshold"):
        result[name] = integer(result.get(name), name)
    if not 0 <= result["background_lower"] < result["background_upper"] <= 255:
        raise ValueError("person_c background bounds must satisfy 0 <= lower < upper <= 255")
    if result.get("device", "auto") not in {"auto", "cpu", "cuda"}:
        raise ValueError("person_c device must be auto, cpu, or cuda")
    result["device"] = result.get("device", "auto")
    if not isinstance(result.get("save_roi_png", False), bool):
        raise ValueError("person_c save_roi_png must be boolean")
    result["save_roi_png"] = result.get("save_roi_png", False)
    if result["save_roi_png"] and not result.get("roi_output_dir"):
        raise ValueError("person_c roi_output_dir is required when save_roi_png is true")
    return result


def slide_mpp(slide: Any) -> tuple[float, float]:
    import openslide

    x = slide.properties.get(openslide.PROPERTY_NAME_MPP_X)
    y = slide.properties.get(openslide.PROPERTY_NAME_MPP_Y)
    try:
        return positive_number(float(x), "WSI mpp_x"), positive_number(float(y), "WSI mpp_y")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"WSI MPP is missing or invalid: x={x!r}, y={y!r}") from exc


def read_level(slide: Any, mpp: tuple[float, float], target_mpp: float) -> int:
    candidates = [
        level for level, downsample in enumerate(slide.level_downsamples)
        if all(axis * float(downsample) <= target_mpp * 1.01 for axis in mpp)
    ]
    return max(candidates) if candidates else 0


def read_rgb(slide: Any, x: int, y: int, level: int, width: int, height: int) -> Any:
    import numpy as np

    downsample = float(slide.level_downsamples[level])
    image = slide.read_region((floor(x * downsample), floor(y * downsample)), level, (width, height))
    try:
        rgb = image.convert("RGB")
        try:
            return np.asarray(rgb).copy()
        finally:
            rgb.close()
    finally:
        image.close()


def read_padded_rgb(slide: Any, x: int, y: int, level: int, size: int) -> Any:
    import numpy as np

    width, height = slide.level_dimensions[level]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(width, x + size), min(height, y + size)
    result = np.full((size, size, 3), 255, dtype=np.uint8)
    if x1 > x0 and y1 > y0:
        result[y0-y:y1-y, x0-x:x1-x] = read_rgb(slide, x0, y0, level, x1-x0, y1-y0)
    return result


def patch_locations(slide: Any, mpp: tuple[float, float], settings: dict[str, Any]) -> Iterator[tuple[int, int]]:
    import cv2
    import numpy as np

    level = read_level(slide, mpp, mpp[0])
    width, height = slide.level_dimensions[level]
    cols, rows = width // settings["stride"], height // settings["stride"]
    if not cols or not rows:
        return
    check_level = read_level(slide, mpp, settings["check_mpp"])
    check_width, check_height = slide.level_dimensions[check_level]
    overview = read_rgb(slide, 0, 0, check_level, check_width, check_height)
    grid = cv2.resize(overview, (cols, rows), interpolation=cv2.INTER_LINEAR)
    average = grid.mean(axis=2)
    tissue = ((average >= settings["background_lower"]) &
              (average <= settings["background_upper"])).astype(np.uint8)
    kernel = np.ones((settings["background_dilation_kernel"],) * 2, dtype=np.uint8)
    tissue = cv2.dilate(tissue, kernel, iterations=1)
    for row, col in np.argwhere(tissue):
        yield int(col) * settings["stride"], int(row) * settings["stride"]


def mask_shape(slide: Any, mpp: tuple[float, float], target_mpp: float) -> tuple[int, int]:
    width, height = slide.level_dimensions[0]
    return ceil(height * mpp[1] / target_mpp), ceil(width * mpp[0] / target_mpp)


def draw_mask(result: Any, mask: Any, x: int, y: int, lower: int, upper: int,
              source_mpp: tuple[float, float], target_mpp: float,
              source_size: tuple[int, int]) -> None:
    import cv2
    import numpy as np

    width, height = source_size
    x0, y0 = max(0, x + lower), max(0, y + lower)
    x1, y1 = min(width, x + upper), min(height, y + upper)
    if x1 <= x0 or y1 <= y0:
        return
    crop = np.asarray(mask)[y0-y:y1-y, x0-x:x1-x]
    if not crop.any():
        return
    dx0 = max(0, min(result.shape[1], floor(x0 * source_mpp[0] / target_mpp)))
    dy0 = max(0, min(result.shape[0], floor(y0 * source_mpp[1] / target_mpp)))
    dx1 = max(0, min(result.shape[1], ceil(x1 * source_mpp[0] / target_mpp)))
    dy1 = max(0, min(result.shape[0], ceil(y1 * source_mpp[1] / target_mpp)))
    if dx1 > dx0 and dy1 > dy0:
        scaled = cv2.resize(crop.astype(np.float32), (dx1-dx0, dy1-dy0), interpolation=cv2.INTER_AREA) > 0
        result[dy0:dy1, dx0:dx1] |= scaled


def load_model(settings: dict[str, Any]) -> tuple[Any, Any]:
    import torch
    from .model.MRCPS_inference_model import MRCPS

    path = resolve_person_reference_path("person_c", settings["model"]["path"])
    if not path.is_file():
        raise FileNotFoundError(f"person_c model weight is missing: {path}")
    revision = settings["model"].get("revision")
    if revision is not None:
        if not isinstance(revision, str) or not revision.startswith("sha256:"):
            raise ValueError("person_c model.revision must use sha256:<digest>")
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != revision.removeprefix("sha256:"):
            raise ValueError(f"person_c model checksum mismatch: {path}")
    device_name = settings["device"]
    if device_name == "auto":
        device_name = "cuda" if torch.cuda.is_available() else "cpu"
    if device_name == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("person_c CUDA was requested but is unavailable")
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or "model_state_dict" not in checkpoint:
        raise ValueError("person_c model checkpoint lacks model_state_dict")
    model = MRCPS()
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.to(device_name).eval()
    return model, torch.device(device_name)


def infer_mask(slide: Any, mpp: tuple[float, float], settings: dict[str, Any], model: Any, device: Any) -> Any:
    import numpy as np
    import torch

    patch = settings["patch_size"]
    stride = settings["stride"]
    low_ratio = settings["low_resolution_ratio"]
    level = read_level(slide, mpp, mpp[0])
    downsample = float(slide.level_downsamples[level])
    source_mpp = (mpp[0] * downsample, mpp[1] * downsample)
    low_level = read_level(slide, mpp, source_mpp[0] * low_ratio)
    low_coord_ratio = float(slide.level_downsamples[low_level]) / downsample
    low_shift = patch // 2 - patch // low_ratio // 2
    result = np.zeros(mask_shape(slide, mpp, settings["postprocess_mpp"]), dtype=bool)
    lower, upper = (patch-stride)//2, (patch-stride)//2 + stride
    batch: list[tuple[int, int, Any, Any]] = []

    def flush() -> None:
        if not batch:
            return
        images = torch.from_numpy(np.stack([item[2] for item in batch]).transpose(0, 3, 1, 2).copy()).to(
            device=device, dtype=torch.float32
        ) / 255.0
        low_images = torch.from_numpy(np.stack([item[3] for item in batch]).transpose(0, 3, 1, 2).copy()).to(
            device=device, dtype=torch.float32
        ) / 255.0
        with torch.inference_mode():
            masks = model(images, low_images).to(torch.uint8).cpu().numpy()
        for (x, y, _, _), mask in zip(batch, masks):
            draw_mask(result, mask, x, y, lower, upper, source_mpp,
                      settings["postprocess_mpp"], slide.level_dimensions[level])
        batch.clear()

    for x, y in patch_locations(slide, mpp, settings):
        image = read_padded_rgb(slide, x, y, level, patch)
        low_x, low_y = round(x / low_coord_ratio) - low_shift, round(y / low_coord_ratio) - low_shift
        low_image = read_padded_rgb(slide, low_x, low_y, low_level, patch)
        batch.append((x, y, image, low_image))
        if len(batch) == settings["batch_size"]:
            flush()
    flush()
    return result


def level0_boxes(mask: Any, mpp: tuple[float, float], size: tuple[int, int], settings: dict[str, Any]) -> list[list[int]]:
    from scipy import ndimage
    from skimage.morphology import dilation, disk, remove_small_holes, remove_small_objects

    clean = remove_small_holes(mask, area_threshold=settings["hole_area_threshold"])
    clean = dilation(clean, disk(1))
    clean = remove_small_objects(clean, min_size=settings["min_object_size"])
    labeled, _ = ndimage.label(clean)
    target = settings["postprocess_mpp"]
    width, height = size
    boxes = []
    for slices in ndimage.find_objects(labeled):
        if slices is None:
            continue
        ys, xs = slices
        x0, y0 = max(0, min(width, floor(xs.start*target/mpp[0]))), max(0, min(height, floor(ys.start*target/mpp[1])))
        x1, y1 = max(0, min(width, ceil(xs.stop*target/mpp[0]))), max(0, min(height, ceil(ys.stop*target/mpp[1])))
        if x1 > x0 and y1 > y0:
            boxes.append([x0, y0, x1-x0, y1-y0])
    return boxes


def target_mpp(area: int) -> float:
    for cutoff, mpp in ((1, 0.25), (4, 0.5), (16, 1.0), (64, 2.0), (256, 4.0), (1024, 8.0)):
        if area <= cutoff * 1_000_000:
            return mpp
    return 16.0


def normalized_box(box: list[int], size: tuple[int, int]) -> list[float]:
    x, y, width, height = box
    full_width, full_height = size
    return [(x+width/2)/full_width, (y+height/2)/full_height,
            width/full_width, height/full_height]


def main_box(box: list[int], mpp: tuple[float, float], target: float,
             size: tuple[int, int]) -> tuple[list[int], tuple[int, int]]:
    full_width, full_height = size
    main_width, main_height = ceil(full_width*mpp[0]/target), ceil(full_height*mpp[1]/target)
    x, y, width, height = box
    x0, y0 = floor(x*mpp[0]/target), floor(y*mpp[1]/target)
    x1, y1 = min(main_width, ceil((x+width)*mpp[0]/target)), min(main_height, ceil((y+height)*mpp[1]/target))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"person_c ROI collapsed at main MPP: {box}")
    return [x0, y0, x1-x0, y1-y0], (main_width, main_height)


def roi_info(box: list[int], size: tuple[int, int], mpp: Any,
             path: str | None = None) -> dict[str, Any]:
    return {"area": box[2]*box[3], "coords_seg": None,
            "cxcywh": normalized_box(box, size), "mpp": mpp,
            "roi_path": path, "roi_wh": box[2:], "xywh": box}


def roi_id(case_id: str, stain_id: str, box: list[int]) -> str:
    key = f"{case_id}\0{stain_id}\0{','.join(map(str, box))}"
    return f"{case_id}-{stain_id}-roi-{sha256(key.encode()).hexdigest()[:16]}"


def save_png(slide: Any, box: list[int], output_size: tuple[int, int], target: float,
             mpp: tuple[float, float], output_dir: Path, identifier: str) -> str:
    from PIL import Image

    x, y, width, height = box
    level = read_level(slide, mpp, target)
    downsample = float(slide.level_downsamples[level])
    region = slide.read_region((x, y), level, (max(1, ceil(width/downsample)), max(1, ceil(height/downsample))))
    try:
        rgb = region.convert("RGB")
        try:
            if rgb.size != output_size:
                resized = rgb.resize(output_size, Image.Resampling.BICUBIC)
                rgb.close()
                rgb = resized
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / (sha256(identifier.encode()).hexdigest()[:24] + ".png")
            temp_path = path.with_suffix(".png.tmp")
            try:
                rgb.save(temp_path, format="PNG")
                temp_path.replace(path)
            finally:
                temp_path.unlink(missing_ok=True)
            return str(path)
        finally:
            rgb.close()
    finally:
        region.close()
