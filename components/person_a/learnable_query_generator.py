"""Gemma 3 condition soft-prompt inference for Person A query generation.

This module is the production inference boundary distilled from the Nano5
training/evaluation programs.  It deliberately does not contain the training
loop, patient reports, the base model, or the learned checkpoint.  Those large
or controlled assets stay outside the repository and are mounted at runtime.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from components.person_a.asset_integrity import verify_external_asset
from contracts.paths import resolve_person_reference_path

SOFT_PROMPT_MARKER = "<SOFT_PROMPT_INSERT>"
TARGET_FORMAT = "chunk_visual_attribute_option_conditions_v2"
CONDITION_LABELS = {
    "Must_True",
    "Must_False",
    "High_Possibly_True",
    "Low_Possibly_True",
    "Negligible",
    "Not_Mentioned",
}


class LearnableQueryGenerationError(ValueError):
    """Raised when model inputs or generated attributes are not usable."""


def _flatten(document: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten(value, path))
        else:
            flattened[path] = value
    return flattened


def _node_types(document: dict[str, Any], prefix: str = "") -> dict[str, str]:
    types: dict[str, str] = {}
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        types[path] = "object" if isinstance(value, dict) else "leaf"
        if isinstance(value, dict):
            types.update(_node_types(value, path))
    return types


def load_attribute_reference(
    path: str | Path,
) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, str]]:
    """Load and validate the condition-annotated Stage 2 chunk reference."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Attribute reference was not found: {source}")
    raw = source.read_bytes()
    chunks = json.loads(raw.decode("utf-8"))
    if not isinstance(chunks, list) or not chunks:
        raise LearnableQueryGenerationError(
            "Attribute reference must be a non-empty JSON array"
        )

    attributes: list[dict[str, Any]] = []
    typelevel_sha256: str | None = None
    for index, item in enumerate(chunks):
        if not isinstance(item, dict) or not isinstance(item.get("attribute"), dict):
            raise LearnableQueryGenerationError(
                f"Attribute reference entry {index} has no attribute object"
            )
        metadata = item.get("attribute_condition_metadata")
        if not isinstance(metadata, dict):
            raise LearnableQueryGenerationError(
                f"Attribute reference entry {index} lacks condition metadata"
            )
        if metadata.get("target_format") != TARGET_FORMAT:
            raise LearnableQueryGenerationError(
                f"Attribute reference entry {index} is not {TARGET_FORMAT}"
            )
        entry_typelevel_sha256 = metadata.get("typelevel_sha256")
        if not isinstance(entry_typelevel_sha256, str) or len(entry_typelevel_sha256) != 64:
            raise LearnableQueryGenerationError(
                f"Attribute reference entry {index} has invalid typelevel_sha256"
            )
        if typelevel_sha256 is None:
            typelevel_sha256 = entry_typelevel_sha256
        elif entry_typelevel_sha256 != typelevel_sha256:
            raise LearnableQueryGenerationError(
                "Attribute reference mixes different type-level revisions"
            )
        text = str(item.get("text", ""))
        if metadata.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
            raise LearnableQueryGenerationError(
                f"Attribute reference entry {index} text hash does not match"
            )
        attributes.append(item["attribute"])

    template = deepcopy(attributes[0])
    expected_nodes = _node_types(template)
    for index, attribute in enumerate(attributes):
        if _node_types(attribute) != expected_nodes:
            raise LearnableQueryGenerationError(
                f"Attribute schema differs in reference entry {index}"
            )

    allowed = {leaf_path: set(CONDITION_LABELS) for leaf_path in _flatten(template)}
    for index, attribute in enumerate(attributes):
        for leaf_path, value in _flatten(attribute).items():
            if not isinstance(value, str) or value not in CONDITION_LABELS:
                raise LearnableQueryGenerationError(
                    f"Attribute reference entry {index} has illegal condition "
                    f"at {leaf_path}: {value!r}"
                )

    canonical_chunks = json.dumps(
        chunks,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return template, allowed, {
        "source_name": source.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "target_format": TARGET_FORMAT,
        "typelevel_sha256": str(typelevel_sha256),
        "chunk_data_sha256": hashlib.sha256(canonical_chunks).hexdigest(),
    }


def parse_strict_json_object(text: str) -> dict[str, Any]:
    """Require the complete generation to be exactly one JSON object."""

    stripped = str(text or "").strip()
    if not stripped:
        raise LearnableQueryGenerationError("Model generated an empty response")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LearnableQueryGenerationError(
            f"Model response is not strict JSON: {exc.msg} "
            f"at line {exc.lineno} column {exc.colno}"
        ) from exc
    if not isinstance(parsed, dict):
        raise LearnableQueryGenerationError(
            f"Model response root must be an object, not {type(parsed).__name__}"
        )
    return parsed


def validate_generated_attributes(
    generated: dict[str, Any],
    template: dict[str, Any],
    allowed_values: dict[str, set[str]],
) -> None:
    """Reject incomplete schemas, extra keys, and out-of-vocabulary values."""

    expected_nodes = _node_types(template)
    actual_nodes = _node_types(generated)
    if actual_nodes != expected_nodes:
        missing = sorted(set(expected_nodes) - set(actual_nodes))
        unexpected = sorted(set(actual_nodes) - set(expected_nodes))
        wrong_type = sorted(
            path
            for path in set(expected_nodes) & set(actual_nodes)
            if expected_nodes[path] != actual_nodes[path]
        )
        raise LearnableQueryGenerationError(
            "Generated Attribute schema is not exact; "
            f"missing={missing}, unexpected={unexpected}, wrong_type={wrong_type}"
        )

    errors: list[str] = []
    for path, value in _flatten(generated).items():
        if not isinstance(value, str) or value not in allowed_values[path]:
            errors.append(
                f"{path}: expected exactly one legal condition string, got {value!r}"
            )
    if errors:
        raise LearnableQueryGenerationError(
            "Generated Attribute values are invalid: " + "; ".join(errors)
        )


def _chunk_text(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for index, chunk in enumerate(chunks, start=1):
        content = str(chunk.get("text", "") or "").strip()
        if "Content:" in content:
            content = content.split("Content:", 1)[1].strip()
        if not content:
            raise LearnableQueryGenerationError(
                f"Retrieved chunk {index} has no text"
            )
        parts.append(f"<chunk{index}>\n{content}\n</chunk{index}>")
    return "\n\n".join(parts)


def _user_text(dx_text: str, chunks: list[dict[str, Any]]) -> str:
    """Keep this prompt byte-for-byte aligned with condition-model training."""

    return (
        f"DxText:\n{dx_text}\n\n"
        f"ChunkText:\n{_chunk_text(chunks)}\n\n"
        f"Task:\n"
        f"Generate the visual attribute condition JSON from DxText and the relevant retrieved chunks.\n"
        f"Some retrieved chunks may be unrelated to DxText. Use relevant chunks and ignore unrelated chunks.\n"
        f"For every canonical attribute, include ALL canonical options, each mapped to exactly one condition string.\n"
        f"Allowed conditions: Must_True, Must_False, High_Possibly_True, Low_Possibly_True, Negligible, Not_Mentioned.\n"
        f"For options supported by the relevant chunks, output the subtype-specific condition learned during training.\n"
        f"Predict qualitative occurrence likelihood categories, not merely which options are mentioned.\n"
        f"For options not supported by the relevant chunks, output Not_Mentioned.\n"
        f"Merge evidence across relevant chunks; unrelated chunks must never supply attribute conditions.\n"
        f"Condition labels describe subtype-level occurrence rules, not observations in this patient's tissue.\n"
        f"Use the canonical nested group/attribute/option schema learned during training.\n"
        f"Return the JSON object only, with no markdown, explanation, metadata, options list, or type fields.\n"
        f"Start directly with {{.\n\n"
        f"Attribute:\n{SOFT_PROMPT_MARKER}"
    )


class LearnableSoftPromptGenerator:
    """Load Gemma and one learned prompt, then generate validated attributes."""

    def __init__(self, config: dict[str, Any]):
        self.config = deepcopy(config)
        self.model_name = str(config["model_name"])
        self.model_revision = config.get("model_revision") or None
        self.checkpoint_path = resolve_person_reference_path(
            "person_a", config["checkpoint_path"]
        )
        self.attribute_reference_path = resolve_person_reference_path(
            "person_a", config["attribute_reference_path"]
        )
        self.required_chunk_count = int(config.get("required_chunk_count", 3))
        self.asset_integrity = str(config.get("asset_integrity", "enforce"))
        self.max_input_len = int(config.get("max_input_len", 8192))
        self.max_new_tokens = int(config.get("max_new_tokens", 768))
        self.require_cuda = bool(config.get("require_cuda", True))
        self.dtype_name = str(config.get("dtype", "auto"))
        self.token_env = str(config.get("token_env", "HF_TOKEN"))
        self.device_map_strategy = str(
            config.get("device_map_strategy", "single_device")
        )
        self.gpu_memory_limit = str(
            config.get("gpu_memory_limit", "1200MiB")
        )
        self.cpu_memory_limit = str(
            config.get("cpu_memory_limit", "12GiB")
        )

        if self.required_chunk_count < 1:
            raise ValueError("required_chunk_count must be positive")
        if self.device_map_strategy not in {
            "single_device",
            "auto_cpu_offload",
        }:
            raise ValueError(
                "device_map_strategy must be single_device or auto_cpu_offload"
            )
        checkpoint_integrity = verify_external_asset(
            self.checkpoint_path,
            integrity_mode=self.asset_integrity,
        )
        attribute_integrity = verify_external_asset(
            self.attribute_reference_path,
            integrity_mode=self.asset_integrity,
        )

        (
            self.attribute_template,
            self.allowed_values,
            reference_provenance,
        ) = load_attribute_reference(self.attribute_reference_path)
        reference_provenance.update(attribute_integrity)
        self.provenance = {
            "backend": "learnable_soft_prompt",
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "checkpoint_name": self.checkpoint_path.name,
            "checkpoint_sha256": checkpoint_integrity["sha256"],
            "checkpoint_integrity": checkpoint_integrity,
            "attribute_reference": reference_provenance,
            "required_chunk_count": self.required_chunk_count,
            "target_format": TARGET_FORMAT,
            "device_map_strategy": self.device_map_strategy,
        }
        self._torch: Any = None
        self._tokenizer: Any = None
        self._model: Any = None
        self._soft_prompt: Any = None
        self._soft_prompt_len: int | None = None
        self._device: str | None = None

    def _dtype(self, torch: Any, device: str) -> Any:
        if self.dtype_name == "auto":
            if device == "cpu":
                return torch.float32
            return (
                torch.bfloat16
                if torch.cuda.is_bf16_supported()
                else torch.float16
            )
        choices = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        if self.dtype_name not in choices:
            raise ValueError("dtype must be auto, float16, bfloat16 or float32")
        return choices[self.dtype_name]

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Learnable query generation requires torch and transformers"
            ) from exc

        cuda_available = torch.cuda.is_available()
        if self.require_cuda and not cuda_available:
            raise RuntimeError(
                "Learnable query generation requires CUDA, but no GPU is visible"
            )
        device = "cuda" if cuda_available else "cpu"
        dtype = self._dtype(torch, device)
        token = os.environ.get(self.token_env)
        common: dict[str, Any] = {}
        if self.model_revision:
            common["revision"] = self.model_revision
        if token:
            common["token"] = token

        tokenizer = AutoTokenizer.from_pretrained(self.model_name, **common)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model_kwargs: dict[str, Any] = {
            "dtype": dtype,
            **common,
        }
        if device == "cuda" and self.device_map_strategy == "auto_cpu_offload":
            # Docker Desktop on a 4 GiB display GPU can expose less allocatable
            # CUDA memory than nvidia-smi reports. Keep the original BF16 model
            # precision, but dispatch only a bounded share of its layers to the
            # GPU and retain the rest in host RAM.
            model_kwargs.update(
                {
                    "device_map": "auto",
                    "max_memory": {
                        0: self.gpu_memory_limit,
                        "cpu": self.cpu_memory_limit,
                    },
                    "low_cpu_mem_usage": True,
                    "offload_buffers": True,
                }
            )
            model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                **model_kwargs,
            )
        else:
            model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                **model_kwargs,
            ).to(device)
        model.config.use_cache = True
        model.eval()
        for parameter in model.parameters():
            parameter.requires_grad = False

        checkpoint = torch.load(
            self.checkpoint_path,
            map_location="cpu",
            weights_only=True,
        )
        soft_prompt = checkpoint.get("soft_prompt")
        if soft_prompt is None or soft_prompt.ndim != 2:
            raise LearnableQueryGenerationError(
                "Checkpoint must contain a two-dimensional soft_prompt tensor"
            )
        checkpoint_model = checkpoint.get("model_name")
        if checkpoint_model and checkpoint_model != self.model_name:
            raise LearnableQueryGenerationError(
                f"Checkpoint model {checkpoint_model!r} does not match "
                f"configured model {self.model_name!r}"
            )
        if checkpoint.get("target_format") != TARGET_FORMAT:
            raise LearnableQueryGenerationError(
                "Checkpoint target_format does not match the condition backend"
            )
        if (
            checkpoint.get("typelevel_sha256")
            != self.provenance["attribute_reference"]["typelevel_sha256"]
        ):
            raise LearnableQueryGenerationError(
                "Checkpoint and condition reference use different type-level data"
            )
        if (
            checkpoint.get("chunk_data_sha256")
            != self.provenance["attribute_reference"]["chunk_data_sha256"]
        ):
            raise LearnableQueryGenerationError(
                "Checkpoint and condition reference use different annotated chunks"
            )
        checkpoint_conditions = checkpoint.get("condition_labels")
        if checkpoint_conditions is not None and set(checkpoint_conditions) != CONDITION_LABELS:
            raise LearnableQueryGenerationError(
                "Checkpoint condition labels do not match the runtime vocabulary"
            )
        checkpoint_template = checkpoint.get("canonical_attribute_template")
        if isinstance(checkpoint_template, dict) and _node_types(checkpoint_template) != _node_types(
            self.attribute_template
        ):
            raise LearnableQueryGenerationError(
                "Checkpoint canonical attribute schema does not match the condition reference"
            )
        embedding_size = model.get_input_embeddings().embedding_dim
        if soft_prompt.shape[1] != embedding_size:
            raise LearnableQueryGenerationError(
                f"Checkpoint embedding width {soft_prompt.shape[1]} does not "
                f"match model width {embedding_size}"
            )
        soft_prompt_len = int(
            checkpoint.get("soft_prompt_len", soft_prompt.shape[0])
        )
        if soft_prompt_len != soft_prompt.shape[0]:
            raise LearnableQueryGenerationError(
                "Checkpoint soft_prompt_len does not match its tensor"
            )

        self.provenance.update(
            {
                "checkpoint_run_name": checkpoint.get("run_name"),
                "checkpoint_epoch": checkpoint.get("current_epoch"),
                "soft_prompt_len": soft_prompt_len,
                "gpu_memory_limit": (
                    self.gpu_memory_limit
                    if device == "cuda"
                    and self.device_map_strategy == "auto_cpu_offload"
                    else None
                ),
                "model_device_map": {
                    str(name): str(location)
                    for name, location in getattr(
                        model, "hf_device_map", {}
                    ).items()
                },
            }
        )
        embedding_device = str(model.get_input_embeddings().weight.device)
        if embedding_device == "meta":
            raise RuntimeError("Model input embeddings remained on the meta device")
        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model
        self._soft_prompt = soft_prompt.to(
            device=embedding_device,
            dtype=model.get_input_embeddings().weight.dtype,
        )
        self._soft_prompt_len = soft_prompt_len
        self._device = embedding_device

    def _split_prompt(self, user_text: str) -> dict[str, Any]:
        torch = self._torch
        tokenizer = self._tokenizer
        rendered = tokenizer.apply_chat_template(
            [{"role": "user", "content": user_text}],
            add_generation_prompt=True,
            tokenize=False,
        )
        if SOFT_PROMPT_MARKER not in rendered:
            raise LearnableQueryGenerationError(
                "Tokenizer chat template lost the soft-prompt insertion marker"
            )
        prefix_text, suffix_text = rendered.split(SOFT_PROMPT_MARKER, 1)
        prefix_full = tokenizer(
            prefix_text,
            add_special_tokens=False,
            padding=False,
            return_tensors="pt",
        )
        suffix = tokenizer(
            suffix_text,
            add_special_tokens=False,
            padding=False,
            return_tensors="pt",
        )
        suffix_len = suffix["input_ids"].shape[-1]
        max_prefix_len = max(
            1,
            self.max_input_len - suffix_len - int(self._soft_prompt_len),
        )
        old_side = tokenizer.truncation_side
        tokenizer.truncation_side = "left"
        try:
            prefix = tokenizer(
                prefix_text,
                add_special_tokens=False,
                truncation=True,
                max_length=max_prefix_len,
                padding=False,
                return_tensors="pt",
            )
        finally:
            tokenizer.truncation_side = old_side
        if "attention_mask" not in prefix:
            prefix["attention_mask"] = torch.ones_like(prefix["input_ids"])
        if "attention_mask" not in suffix:
            suffix["attention_mask"] = torch.ones_like(suffix["input_ids"])
        return {"prefix": prefix, "suffix": suffix}

    def generate(
        self,
        dx_text: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not str(dx_text or "").strip():
            raise LearnableQueryGenerationError("DxText is empty")
        if len(chunks) != self.required_chunk_count:
            raise LearnableQueryGenerationError(
                f"The trained soft prompt requires exactly "
                f"{self.required_chunk_count} chunks, received {len(chunks)}"
            )
        self._load()
        torch = self._torch
        model = self._model
        tokenizer = self._tokenizer
        device = self._device
        encoded = self._split_prompt(_user_text(str(dx_text).strip(), chunks))
        prefix_ids = encoded["prefix"]["input_ids"].to(device)
        prefix_mask = encoded["prefix"]["attention_mask"].to(device)
        suffix_ids = encoded["suffix"]["input_ids"].to(device)
        suffix_mask = encoded["suffix"]["attention_mask"].to(device)
        embedding = model.get_input_embeddings()
        model_dtype = embedding.weight.dtype
        prefix_embeds = embedding(prefix_ids).to(dtype=model_dtype)
        suffix_embeds = embedding(suffix_ids).to(dtype=model_dtype)
        soft_embeds = self._soft_prompt.unsqueeze(0).expand(
            prefix_ids.size(0), -1, -1
        )
        inputs_embeds = torch.cat(
            [prefix_embeds, soft_embeds, suffix_embeds], dim=1
        )
        soft_mask = torch.ones(
            prefix_ids.size(0),
            int(self._soft_prompt_len),
            dtype=prefix_mask.dtype,
            device=device,
        )
        attention_mask = torch.cat(
            [prefix_mask, soft_mask, suffix_mask], dim=1
        )
        with torch.inference_mode():
            generated_ids = model.generate(
                inputs_embeds=inputs_embeds,
                attention_mask=attention_mask,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                use_cache=True,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
        generated_text = tokenizer.decode(
            generated_ids[0], skip_special_tokens=True
        )
        generated = parse_strict_json_object(generated_text)
        validate_generated_attributes(
            generated,
            self.attribute_template,
            self.allowed_values,
        )
        return generated
