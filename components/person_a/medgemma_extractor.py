"""Optional per-report MedGemma 1.5 backend adapted from Query_Design.

Imports are intentionally lazy so the standard-library regex/demo path remains
lightweight.  A server selecting this backend must provide a compatible
PyTorch/Transformers environment, GPU and verified local model files.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from components.person_a.local_model_integrity import verify_local_model
from contracts.paths import resolve_person_reference_path


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in {
        "",
        "na",
        "n/a",
        "none",
        "null",
        "not mentioned",
        "not specified",
    }:
        return ""
    return text


def _chunks(text: str, chunk_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if chunk_chars <= overlap:
        raise ValueError("MedGemma chunk_chars must be larger than overlap")
    return [
        text[start : start + chunk_chars]
        for start in range(0, len(text), chunk_chars - overlap)
    ]


def _json_object(generated_text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", generated_text, flags=re.IGNORECASE)
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for start, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects[-1] if objects else {}


def _canonical_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


class MedGemmaExtractor:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.model_id = self.config.get("model_id", "google/medgemma-1.5-4b-it")
        self.model_revision = self.config.get("model_revision")
        self.model_path = resolve_person_reference_path("person_a", self.config["model_path"])
        self.provenance: dict[str, Any] = {}
        self.chunk_chars = int(self.config.get("chunk_chars", 6500))
        self.overlap = int(self.config.get("overlap", 700))
        self.max_input_tokens = int(self.config.get("max_input_tokens", 4096))
        self.max_new_tokens = int(self.config.get("max_new_tokens", 1200))
        self.load_in_4bit = bool(self.config.get("load_in_4bit", True))
        self.enable_cpu_offload = bool(
            self.config.get("enable_cpu_offload", False)
        )
        self.device_map_strategy = str(
            self.config.get("device_map_strategy", "auto")
        )
        self.require_cuda = bool(self.config.get("require_cuda", True))
        self.compute_dtype = str(self.config.get("compute_dtype", "auto"))
        self.capture_generation_diagnostics = bool(
            self.config.get("capture_generation_diagnostics", False)
        )
        self.processor: Any | None = None
        self.model: Any | None = None
        self.last_generated_text = ""
        self.last_generation_token_ids: list[int] = []
        self.last_input_length = 0
        self.last_output_length = 0
        self.last_logits_diagnostics: dict[str, Any] = {}
        self.generation_count = 0

    @staticmethod
    def _native_bf16_available(torch: Any) -> bool:
        if not torch.cuda.is_available():
            return False
        major, _ = torch.cuda.get_device_capability()
        return major >= 8 and torch.cuda.is_bf16_supported()

    def _torch_dtype(self, torch: Any) -> Any:
        if self.compute_dtype == "float16":
            return torch.float16
        if self.compute_dtype == "bfloat16":
            if not torch.cuda.is_bf16_supported():
                raise RuntimeError(
                    "MedGemma compute_dtype=bfloat16 was requested, but this GPU "
                    "is not supported by PyTorch for bfloat16 compute; use auto "
                    "or float16"
                )
            return torch.bfloat16
        if self.compute_dtype != "auto":
            raise ValueError(
                "MedGemma compute_dtype must be auto, float16 or bfloat16"
            )
        if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
            return torch.bfloat16
        if torch.cuda.is_available():
            return torch.float16
        return torch.float32

    def _load(self) -> None:
        if self.model is not None:
            return
        integrity = verify_local_model(
            self.model_path, model_id=self.model_id, revision=self.model_revision,
        )
        try:
            import torch
            from transformers import (
                AutoModelForImageTextToText,
                AutoProcessor,
                BitsAndBytesConfig,
            )
        except ImportError as exc:
            raise RuntimeError(
                "MedGemma backend requires torch, transformers, accelerate and "
                "bitsandbytes in person A's server environment"
            ) from exc

        if self.require_cuda and not torch.cuda.is_available():
            raise RuntimeError(
                "MedGemma backend requires CUDA, but PyTorch cannot see a GPU. "
                "Run the Person A container with GPU access (for example, "
                "docker run --gpus all)."
            )

        dtype = self._torch_dtype(torch)

        quantization = None
        if self.load_in_4bit:
            quantization = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=dtype,
                bnb_4bit_use_double_quant=True,
                # Despite its historical name, Transformers also checks this
                # flag when a 4-bit device map must leave modules on CPU.
                llm_int8_enable_fp32_cpu_offload=self.enable_cpu_offload,
            )

        if self.device_map_strategy == "auto":
            device_map: str | dict[str, str | int] = "auto"
        elif self.device_map_strategy == "text_gpu_vision_cpu":
            if not torch.cuda.is_available():
                raise RuntimeError(
                    "device_map_strategy=text_gpu_vision_cpu requires CUDA"
                )
            # Report Decompose supplies report text, not pixels.  Keep the
            # text model and output head on the GPU, while the currently
            # unused vision path remains in host RAM.  Keeping each complete
            # quantized subtree on one device also avoids unsupported 4-bit
            # layer-by-layer CPU dispatch.
            device_map = {
                "model.vision_tower": "cpu",
                "model.multi_modal_projector": "cpu",
                "model.language_model": 0,
                "lm_head": 0,
            }
        else:
            raise ValueError(
                "MedGemma device_map_strategy must be auto or "
                "text_gpu_vision_cpu"
            )

        self.processor = AutoProcessor.from_pretrained(
            str(self.model_path), local_files_only=True
        )
        self.processor.tokenizer.pad_token = self.processor.tokenizer.eos_token
        self.model = AutoModelForImageTextToText.from_pretrained(
            str(self.model_path),
            local_files_only=True,
            quantization_config=quantization,
            device_map=device_map,
            dtype=dtype,
            low_cpu_mem_usage=True,
        )
        self.model.config.pad_token_id = self.processor.tokenizer.pad_token_id
        self.model.eval()
        self.provenance = integrity
        logging.getLogger(__name__).info(json.dumps({
            "event": "medgemma_loaded",
            "model_id": self.model_id,
            "configured_revision": self.model_revision,
            "model_integrity": self.provenance,
            "quantization": "bitsandbytes-nf4-4bit" if self.load_in_4bit else "none",
            "compute_dtype": str(dtype),
            "cuda_available": torch.cuda.is_available(),
        }))

    def _extract_chunk(self, chunk: str, items: list[str]) -> dict[str, str]:
        self._load()
        import torch

        system = (
            "You are a pathology information extractor. Use ONLY the provided "
            "report text. Return ONLY one valid JSON object. Do not explain. "
            "If an item is not stated, output an empty string."
        )
        keys = "\n".join(f'- "{item}"' for item in items)
        user = (
            "Fill these fields from the pathology report. Return ONLY JSON "
            "with exactly these keys. Use \"\" if not mentioned.\n\n"
            f"Keys:\n{keys}\n\nReport:\n\"\"\"{chunk}\"\"\""
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        tokenizer = self.processor.tokenizer
        prompt_text = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        encoded = tokenizer(
            prompt_text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_input_tokens,
        )
        language_device = getattr(self.model, "hf_device_map", {}).get(
            "model.language_model", self.model.device
        )
        if isinstance(language_device, int):
            language_device = f"cuda:{language_device}"
        encoded = encoded.to(language_device)
        input_length = encoded["input_ids"].shape[-1]
        with torch.inference_mode():
            output = self.model.generate(
                **encoded,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
                return_dict_in_generate=self.capture_generation_diagnostics,
                output_logits=self.capture_generation_diagnostics,
            )
        if self.capture_generation_diagnostics:
            sequences = output.sequences
            first_logits = output.logits[0]
            finite = torch.isfinite(first_logits)
            self.last_logits_diagnostics = {
                "all_finite": bool(finite.all()),
                "nan_count": int(torch.isnan(first_logits).sum()),
                "inf_count": int(torch.isinf(first_logits).sum()),
                "top_token_ids": torch.topk(first_logits[0], 5).indices.tolist(),
            }
        else:
            sequences = output
        generated = tokenizer.decode(
            sequences[0][input_length:], skip_special_tokens=True
        )
        self.last_input_length = input_length
        self.last_output_length = sequences[0].shape[-1]
        self.last_generation_token_ids = sequences[0][input_length:].tolist()
        self.last_generated_text = generated
        self.generation_count += 1
        logging.getLogger(__name__).info(json.dumps({
            "event": "medgemma_generate_complete",
            "generate_call": self.generation_count,
            "input_tokens": self.last_input_length,
            "generated_tokens": len(self.last_generation_token_ids),
            "items": items,
        }))
        parsed = _json_object(generated)
        normalized = {_canonical_key(key): value for key, value in parsed.items()}
        return {
            item: _clean(normalized.get(_canonical_key(item))) for item in items
        }

    def extract(self, report_text: str, items: list[str]) -> dict[str, str]:
        gross = re.search(
            r"\bGross\s*description\s*[:：]", report_text, flags=re.IGNORECASE
        )
        text = report_text[: gross.start()] if gross else report_text
        merged = {item: "" for item in items}
        for chunk in _chunks(text, self.chunk_chars, self.overlap):
            extracted = self._extract_chunk(chunk, items)
            for item in items:
                if not merged[item] and extracted[item]:
                    merged[item] = extracted[item]
        return {item: value for item, value in merged.items() if value}
