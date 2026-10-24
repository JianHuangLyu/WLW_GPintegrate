"""GPU/runtime smoke check for person A's optional MedGemma image."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _environment() -> dict[str, object]:
    import accelerate
    import bitsandbytes
    import torch
    import transformers
    from transformers import (
        AutoModelForImageTextToText,
        AutoProcessor,
        BitsAndBytesConfig,
    )

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available inside the MedGemma container")
    properties = torch.cuda.get_device_properties(0)
    native_bf16 = properties.major >= 8 and torch.cuda.is_bf16_supported()
    compute_dtype = (
        torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    )
    BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=True,
    )
    layer = bitsandbytes.nn.Linear4bit(
        64,
        64,
        bias=False,
        compute_dtype=compute_dtype,
        quant_type="nf4",
        quant_storage=torch.uint8,
    ).cuda()
    values = torch.randn(1, 64, device="cuda", dtype=compute_dtype)
    with torch.inference_mode():
        output = layer(values)
    if not torch.isfinite(output).all():
        raise RuntimeError("bitsandbytes 4-bit CUDA smoke produced non-finite values")
    del layer, values, output
    torch.cuda.empty_cache()
    return {
        "status": "ok",
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "transformers": transformers.__version__,
        "accelerate": accelerate.__version__,
        "bitsandbytes": bitsandbytes.__version__,
        "gpu": properties.name,
        "gpu_vram_gib": round(properties.total_memory / 1024**3, 2),
        "compute_capability": f"{properties.major}.{properties.minor}",
        "torch_bf16_supported": torch.cuda.is_bf16_supported(),
        "native_bf16_supported": native_bf16,
        "selected_compute_dtype": (
            "bfloat16" if torch.cuda.is_bf16_supported() else "float16"
        ),
        "medgemma_transformers_api": (
            f"{AutoProcessor.__name__}+{AutoModelForImageTextToText.__name__}"
        ),
        "bitsandbytes_4bit_cuda": "ok",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check MedGemma GPU runtime")
    parser.add_argument(
        "--load-model",
        action="store_true",
        help="also verify/load local MedGemma and perform one short generation",
    )
    parser.add_argument(
        "--config",
        default="/app/components/person_a/configs/report_decompose.default.json",
        help="Report Decompose config used by --load-model",
    )
    args = parser.parse_args()

    result = _environment()
    if args.load_model:
        from components.person_a.medgemma_extractor import MedGemmaExtractor

        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        medgemma_config = dict(config["report_extraction"]["medgemma"])
        medgemma_config["max_input_tokens"] = min(
            int(medgemma_config.get("max_input_tokens", 512)), 512
        )
        medgemma_config["max_new_tokens"] = min(
            int(medgemma_config.get("max_new_tokens", 96)), 96
        )
        medgemma_config["capture_generation_diagnostics"] = True
        extractor = MedGemmaExtractor(medgemma_config)
        result["generation"] = extractor.extract(
            "Histologic Type: invasive carcinoma of no special type.",
            ["Histologic_Type"],
        )
        result["model_integrity"] = extractor.provenance
        result["generation_diagnostics"] = {
            "input_tokens": extractor.last_input_length,
            "output_tokens": extractor.last_output_length,
            "new_token_ids": extractor.last_generation_token_ids[:16],
            "first_step_logits": extractor.last_logits_diagnostics,
        }
        if not result["generation"].get("Histologic_Type"):
            raise RuntimeError(
                "MedGemma loaded but did not extract Histologic_Type"
            )
        if not extractor.last_logits_diagnostics.get("all_finite"):
            raise RuntimeError("MedGemma generation produced non-finite logits")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
