"""Person D visual attribute extraction with PLIP and CONCH.

Ported from ``pipeline_quilt_1m.py``.  The scoring method is unchanged: option
prompt embeddings (with prompt chunking), few-shot example prototypes, the
custom text prompt prior, single/multi-select prediction, and PLIP/CONCH
agreement.  Quilt-1M dataset handling (CSV lookup, QuiltCleaner filtering,
label-folder copying, and resume logs) is not part of the WLW component.

Runtime differences required by the WLW contract:

* vocabulary, option descriptions, and prompts come from
  ``reference/person_d/template_ref``; weights and hyperparameters from config;
* weights load from local files only, and the configured device is mandatory;
* an unreadable example image raises instead of being skipped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import torch
import torch.nn.functional as F
from PIL import Image

from components.person_d.assets import (
    EXAMPLE_IMAGE_EXTENSIONS,
    PLIP_SUPPORT_FILES,
    check_digest,
    file_sha256,
    get_example_option_folder_candidates,
    required_digest,
    required_digests,
    tree_sha256,
    validate_example_layout,
)
from contracts.paths import resolve_person_reference_path, sibling_logical_path


MODEL_NAMES = ("PLIP", "CONCH")


@dataclass(frozen=True)
class Vocabulary:
    attributes: Dict[str, Dict[str, List[str]]]
    multi_select_attributes: frozenset
    prompt_descriptions: Dict[str, Any]


@dataclass(frozen=True)
class ExtractionSettings:
    image_score_weight: float
    text_score_weight: float
    example_score_weight: float
    use_custom_text_prompt: bool
    use_example_prototypes: bool
    multi_select_margin: float
    copy_na_labels: bool
    enable_prompt_chunking: bool
    token_safety_margin: int
    fallback_words_per_chunk: int

    @classmethod
    def from_config(cls, raw: Mapping[str, Any]) -> "ExtractionSettings":
        try:
            settings = cls(
                image_score_weight=float(raw["image_score_weight"]),
                text_score_weight=float(raw["text_score_weight"]),
                example_score_weight=float(raw["example_score_weight"]),
                use_custom_text_prompt=bool(raw["use_custom_text_prompt"]),
                use_example_prototypes=bool(raw["use_example_prototypes"]),
                multi_select_margin=float(raw["multi_select_margin"]),
                copy_na_labels=bool(raw["copy_na_labels"]),
                enable_prompt_chunking=bool(raw["enable_prompt_chunking"]),
                token_safety_margin=int(raw["token_safety_margin"]),
                fallback_words_per_chunk=int(raw["fallback_words_per_chunk"]),
            )
        except KeyError as exc:
            raise ValueError(f"Person D extraction config is missing {exc.args[0]!r}") from exc
        if settings.fallback_words_per_chunk <= 0 or settings.token_safety_margin < 0:
            raise ValueError("Person D prompt chunking settings must be positive")
        return settings


def load_vocabulary(document: Mapping[str, Any]) -> Vocabulary:
    attributes = document["attributes"]
    multi_select = frozenset(document["multi_select_attributes"])
    known = {attr for attrs in attributes.values() for attr in attrs}
    if not multi_select <= known:
        raise ValueError(f"Unknown multi-select attributes: {sorted(multi_select - known)}")
    return Vocabulary(
        attributes=attributes,
        multi_select_attributes=multi_select,
        prompt_descriptions=document["prompt_descriptions"],
    )


# ============================================================
# Utility
# ============================================================

def resolve_example_analysis_root(example_dir: Path) -> Path:
    """
    Accept either:
        ./Example
    or:
        ./Example/ROI_Analysis

    Return the actual ROI_Analysis root used for reading example folders.
    """
    example_dir = Path(example_dir)

    if example_dir.name == "ROI_Analysis":
        return example_dir

    candidate = example_dir / "ROI_Analysis"
    if candidate.exists():
        return candidate

    # Fallback: allow users to pass a custom root that already contains group folders.
    return example_dir


def resolve_example_option_dir(
    example_analysis_root: Path,
    group: str,
    attribute: str,
    option: str,
) -> Optional[Path]:
    base_dir = Path(example_analysis_root) / group / attribute

    for folder_name in get_example_option_folder_candidates(option):
        candidate = base_dir / folder_name
        if candidate.exists() and candidate.is_dir():
            return candidate

    return None


def collect_example_images_for_option(
    example_analysis_root: Path,
    group: str,
    attribute: str,
    option: str,
) -> List[Path]:
    option_dir = resolve_example_option_dir(
        example_analysis_root=example_analysis_root,
        group=group,
        attribute=attribute,
        option=option,
    )

    if option_dir is None:
        return []

    image_paths = [
        p
        for p in option_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in EXAMPLE_IMAGE_EXTENSIONS
    ]

    return sorted(image_paths)


def normalize_prompt_list(prompts: Optional[List[str]]) -> List[str]:
    if prompts is None:
        return []

    return [str(prompt).strip() for prompt in prompts if str(prompt).strip()]


def get_option_description(
    vocabulary: Vocabulary, group: str, attribute: str, option: str
) -> str:
    group_desc = vocabulary.prompt_descriptions.get(group, {})
    attr_desc = group_desc.get(attribute, {}) if isinstance(group_desc, dict) else {}

    if isinstance(attr_desc, dict) and option in attr_desc:
        return attr_desc[option]

    general_rules = vocabulary.prompt_descriptions.get("General_Label_Rules", {})
    if option in general_rules:
        return general_rules[option]

    return f"The ROI shows the visual attribute {attribute}: {option}."


def get_model_max_text_tokens(model_wrapper) -> int:
    return int(getattr(model_wrapper, "max_text_tokens", 77))


def count_prompt_tokens(model_wrapper, text: str) -> Optional[int]:
    if hasattr(model_wrapper, "get_text_token_counts"):
        try:
            counts = model_wrapper.get_text_token_counts([text])
            if counts and counts[0] is not None:
                return int(counts[0])
        except Exception:
            return None

    return None


def chunk_words_by_token_limit(
    model_wrapper,
    prefix: str,
    body: str,
    settings: ExtractionSettings,
    suffix: str = "",
    max_tokens: Optional[int] = None,
) -> List[str]:
    """
    將 body 切成多段，讓 prefix + body_chunk + suffix 盡量不超過模型 token 上限。
    回傳完整 prompt chunk list。
    """
    if max_tokens is None:
        max_tokens = get_model_max_text_tokens(model_wrapper)

    effective_max_tokens = max(8, max_tokens - settings.token_safety_margin)
    full_text = f"{prefix}{body}{suffix}"
    full_count = count_prompt_tokens(model_wrapper, full_text)

    if not settings.enable_prompt_chunking:
        return [full_text]

    words_per_chunk = settings.fallback_words_per_chunk

    if full_count is None:
        # 無法可靠計算 token 時，退回 word-based chunk。
        words = body.split()
        if len(words) <= words_per_chunk:
            return [full_text]

        chunks = []
        for i in range(0, len(words), words_per_chunk):
            chunk_body = " ".join(words[i:i + words_per_chunk])
            chunks.append(f"{prefix}{chunk_body}{suffix}")
        return chunks

    if full_count <= effective_max_tokens:
        return [full_text]

    words = body.split()
    chunks: List[str] = []
    current_words: List[str] = []

    for word in words:
        candidate_words = current_words + [word]
        candidate_body = " ".join(candidate_words)
        candidate_prompt = f"{prefix}{candidate_body}{suffix}"
        candidate_count = count_prompt_tokens(model_wrapper, candidate_prompt)

        if candidate_count is not None and candidate_count <= effective_max_tokens:
            current_words.append(word)
            continue

        if candidate_count is None and len(candidate_words) <= words_per_chunk:
            current_words.append(word)
            continue

        if current_words:
            chunk_body = " ".join(current_words)
            chunks.append(f"{prefix}{chunk_body}{suffix}")
            current_words = [word]
        else:
            # 極端情況：單一 word 或 prefix 太長，仍保留，讓 tokenizer 處理。
            chunks.append(candidate_prompt)
            current_words = []

    if current_words:
        chunk_body = " ".join(current_words)
        chunks.append(f"{prefix}{chunk_body}{suffix}")

    return chunks if chunks else [full_text]


def make_option_prompt_chunks(
    model_wrapper,
    vocabulary: Vocabulary,
    settings: ExtractionSettings,
    group: str,
    attribute: str,
    option: str,
    template: str,
) -> List[str]:
    """
    將過長的 option prompt 切成多段。
    每一段都保留 Attribute / Label，只切 Visual definition。
    """
    description = get_option_description(vocabulary, group, attribute, option)

    default_prompt = template.format(
        group=group,
        attribute=attribute,
        option=option,
        description=description,
    )

    full_count = count_prompt_tokens(model_wrapper, default_prompt)
    max_tokens = get_model_max_text_tokens(model_wrapper)
    effective_max_tokens = max(8, max_tokens - settings.token_safety_margin)

    if not settings.enable_prompt_chunking:
        return [default_prompt]

    if full_count is not None and full_count <= effective_max_tokens:
        return [default_prompt]

    # 用空 description 估計 prefix。
    prefix_prompt = template.format(
        group=group,
        attribute=attribute,
        option=option,
        description="",
    )

    # 如果 template 裡 description 在最後，這個方式最乾淨。
    if default_prompt.startswith(prefix_prompt):
        return chunk_words_by_token_limit(
            model_wrapper=model_wrapper,
            prefix=prefix_prompt,
            body=description,
            settings=settings,
            suffix="",
            max_tokens=max_tokens,
        )

    # 若使用者自訂 template，且 description 不在最後，則退回通用切法：
    # 每段仍重新套用 template，但 description 換成該 chunk。
    words = description.split()
    chunks: List[str] = []
    current_words: List[str] = []

    for word in words:
        candidate_words = current_words + [word]
        candidate_description = " ".join(candidate_words)
        candidate_prompt = template.format(
            group=group,
            attribute=attribute,
            option=option,
            description=candidate_description,
        )
        candidate_count = count_prompt_tokens(model_wrapper, candidate_prompt)

        if candidate_count is not None and candidate_count <= effective_max_tokens:
            current_words.append(word)
        elif (
            candidate_count is None
            and len(candidate_words) <= settings.fallback_words_per_chunk
        ):
            current_words.append(word)
        else:
            if current_words:
                chunk_description = " ".join(current_words)
                chunks.append(
                    template.format(
                        group=group,
                        attribute=attribute,
                        option=option,
                        description=chunk_description,
                    )
                )
                current_words = [word]
            else:
                chunks.append(candidate_prompt)
                current_words = []

    if current_words:
        chunk_description = " ".join(current_words)
        chunks.append(
            template.format(
                group=group,
                attribute=attribute,
                option=option,
                description=chunk_description,
            )
        )

    return chunks if chunks else [default_prompt]


def make_free_text_prompt_chunks(
    model_wrapper, text: str, settings: ExtractionSettings
) -> List[str]:
    """
    給 custom text prompt 使用。
    很長的 custom prompt 也會分段 encode。
    """
    return chunk_words_by_token_limit(
        model_wrapper=model_wrapper,
        prefix="",
        body=text,
        settings=settings,
        suffix="",
        max_tokens=get_model_max_text_tokens(model_wrapper),
    )


# ============================================================
# PLIP Wrapper
# ============================================================

class PLIPZeroShot:
    def __init__(self, weight_path: Path, device: str):
        from transformers import CLIPModel, CLIPProcessor

        self.device = device

        # 不要加 use_fast=False。
        # 否則在某些 transformers / tokenizer 環境下會觸發 slow tokenizer + protobuf 錯誤。
        self.processor = CLIPProcessor.from_pretrained(weight_path, local_files_only=True)
        self.model = CLIPModel.from_pretrained(weight_path, local_files_only=True).to(device)
        self.model.eval()

        # PLIP/CLIP text encoder 通常最大長度是 77 tokens。
        self.max_text_tokens = int(
            getattr(self.model.config.text_config, "max_position_embeddings", 77)
        )

    @torch.no_grad()
    def encode_image(self, image: Image.Image) -> torch.Tensor:
        inputs = self.processor(
            images=image,
            return_tensors="pt",
        ).to(self.device)

        emb = self.model.get_image_features(**inputs)
        emb = F.normalize(emb, dim=-1)

        return emb

    @torch.no_grad()
    def encode_texts(self, texts: List[str]) -> torch.Tensor:
        """
        PLIP 底層是 CLIP text encoder，文字長度不能超過 max_text_tokens。
        這裡保留 truncation=True，作為安全保護。
        真正避免資訊遺失的方式是在 AttributeClassifier 初始化時先 chunk prompts。
        """
        inputs = self.processor(
            text=texts,
            padding=True,
            truncation=True,
            max_length=self.max_text_tokens,
            return_tensors="pt",
        ).to(self.device)

        emb = self.model.get_text_features(**inputs)
        emb = F.normalize(emb, dim=-1)

        return emb

    def get_text_token_counts(self, texts: List[str]) -> List[int]:
        """
        計算原始 prompt 的 token 數。
        注意：這裡不截斷，用來知道原本 prompt 是否超過 77。
        """
        encoded = self.processor.tokenizer(
            texts,
            padding=False,
            truncation=False,
            add_special_tokens=True,
        )

        return [len(ids) for ids in encoded["input_ids"]]

    def get_effective_texts(self, texts: List[str]) -> List[str]:
        """
        回傳 PLIP 實際吃到的 prompt。
        也就是經過 max_length 截斷後，再 decode 回文字。
        """
        encoded = self.processor.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_text_tokens,
            return_tensors="pt",
        )

        effective_texts = []

        for input_ids, attention_mask in zip(
            encoded["input_ids"],
            encoded["attention_mask"],
        ):
            valid_ids = input_ids[attention_mask.bool()].tolist()

            text = self.processor.tokenizer.decode(
                valid_ids,
                skip_special_tokens=True,
            )

            effective_texts.append(text)

        return effective_texts


# ============================================================
# CONCH Wrapper
# ============================================================

class CONCHZeroShot:
    def __init__(self, model_name: str, checkpoint_path: Path, device: str):
        self.device = device

        from conch.open_clip_custom import (
            create_model_from_pretrained,
            get_tokenizer,
            tokenize,
        )

        self.tokenize_fn = tokenize
        self.tokenizer = get_tokenizer()

        self.model, self.preprocess = create_model_from_pretrained(
            model_name,
            checkpoint_path=str(checkpoint_path),
            device=device,
        )

        self.model = self.model.to(device)
        self.model.eval()

        # 大部分 CLIP/OpenCLIP/CONCH text context length 為 77。
        # 不同版本 model 可能有 context_length attribute，沒有就用 77。
        self.max_text_tokens = int(getattr(self.model, "context_length", 77))

    @torch.no_grad()
    def encode_image(self, image: Image.Image) -> torch.Tensor:
        image_tensor = self.preprocess(image).unsqueeze(0).to(self.device)

        emb = self.model.encode_image(
            image_tensor,
            proj_contrast=True,
            normalize=True,
        )

        emb = F.normalize(emb, dim=-1)

        return emb

    @torch.no_grad()
    def encode_texts(self, texts: List[str]) -> torch.Tensor:
        """
        CONCH 的 tokenize 在不同版本可能支援不同參數。
        這裡先嘗試傳 context_length，不支援時再退回原本呼叫方式。
        prompt chunking 會在 AttributeClassifier 初始化時處理。
        """
        try:
            tokens = self.tokenize_fn(
                texts=texts,
                tokenizer=self.tokenizer,
                context_length=self.max_text_tokens,
            ).to(self.device)
        except TypeError:
            tokens = self.tokenize_fn(
                texts=texts,
                tokenizer=self.tokenizer,
            ).to(self.device)

        emb = self.model.encode_text(tokens)
        emb = F.normalize(emb, dim=-1)

        return emb

    def get_text_token_counts(self, texts: List[str]) -> List[Optional[int]]:
        counts: List[Optional[int]] = []

        for text in texts:
            try:
                if hasattr(self.tokenizer, "encode"):
                    ids = self.tokenizer.encode(text)
                    counts.append(len(ids))
                    continue

                encoded = self.tokenizer(text)

                if isinstance(encoded, dict) and "input_ids" in encoded:
                    ids = encoded["input_ids"]
                    if hasattr(ids, "tolist"):
                        ids = ids.tolist()
                    counts.append(len(ids))
                elif isinstance(encoded, list):
                    counts.append(len(encoded))
                else:
                    counts.append(None)
            except Exception:
                counts.append(None)

        return counts

    def get_effective_texts(self, texts: List[str]) -> List[str]:
        # CONCH 的 tokenizer 不一定有穩定 decode API。
        # 因為本程式已經先 chunk，所以這裡回傳 chunk 後的 prompt。
        return texts


# ============================================================
# Zero-shot Classifier
# ============================================================

class AttributeClassifier:
    def __init__(
        self,
        model_wrapper,
        vocabulary: Vocabulary,
        settings: ExtractionSettings,
        option_prompt_template: str,
        custom_text_prompts: Optional[List[str]] = None,
        example_dir: Optional[Path] = None,
    ):
        self.model = model_wrapper
        self.vocabulary = vocabulary
        self.settings = settings
        self.option_prompt_template = option_prompt_template
        self.custom_text_prompts = normalize_prompt_list(custom_text_prompts)
        self.use_custom_text_prompt = settings.use_custom_text_prompt
        self.image_score_weight = settings.image_score_weight
        self.text_score_weight = settings.text_score_weight

        self.example_dir = Path(example_dir) if example_dir is not None else None
        self.example_analysis_root = (
            resolve_example_analysis_root(self.example_dir)
            if self.example_dir is not None
            else None
        )
        self.use_example_prototypes = bool(settings.use_example_prototypes)
        self.example_score_weight = float(settings.example_score_weight)

        # Step 1: build text option embeddings.
        self.option_embeddings = self._build_option_embeddings()

        # Step 2: read deterministic Example folders and build visual prototypes.
        # These are not classified. They act as few-shot visual anchors for each option.
        self.example_prototypes = self._build_example_prototypes()
        self.example_metadata = self._build_example_metadata()

        # Step 3: keep the original custom text prompt fusion.
        self.custom_prompt_embedding = self._build_custom_prompt_embedding()

    def _build_option_embeddings(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        一個 option -> 多個 prompt chunks -> 多個 embeddings -> 平均成一個 option embedding。
        """
        cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

        for group_name, attrs in self.vocabulary.attributes.items():
            cache[group_name] = {}

            for attr_name, options in attrs.items():
                option_prompts: List[List[str]] = []
                all_chunk_prompts: List[str] = []
                chunk_spans: List[Tuple[int, int]] = []

                for option in options:
                    chunks = make_option_prompt_chunks(
                        model_wrapper=self.model,
                        vocabulary=self.vocabulary,
                        settings=self.settings,
                        group=group_name,
                        attribute=attr_name,
                        option=option,
                        template=self.option_prompt_template,
                    )

                    start = len(all_chunk_prompts)
                    all_chunk_prompts.extend(chunks)
                    end = len(all_chunk_prompts)

                    option_prompts.append(chunks)
                    chunk_spans.append((start, end))

                all_chunk_emb = self.model.encode_texts(all_chunk_prompts)

                option_embs = []

                for start, end in chunk_spans:
                    chunk_embs = all_chunk_emb[start:end]
                    option_emb = chunk_embs.mean(dim=0, keepdim=True)
                    option_emb = F.normalize(option_emb, dim=-1)
                    option_embs.append(option_emb)

                cache[group_name][attr_name] = {
                    "options": options,
                    "prompts": option_prompts,
                    "embeddings": torch.cat(option_embs, dim=0),
                }

        return cache

    @torch.no_grad()
    def _build_example_prototypes(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        Build one image prototype per ROI option from the Example folder.

        For each option folder:
            example images -> model image embeddings -> mean embedding -> normalize

        If a folder is missing or empty, that option simply has no example prototype.
        The text prompt embedding is still used for that option.
        """
        cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

        if not self.use_example_prototypes or self.example_score_weight <= 0:
            return cache

        if self.example_analysis_root is None or not self.example_analysis_root.exists():
            raise FileNotFoundError(
                f"Example ROI_Analysis folder not found: {self.example_analysis_root}"
            )

        for group_name, attrs in self.vocabulary.attributes.items():
            cache[group_name] = {}

            for attr_name, options in attrs.items():
                option_prototypes: List[torch.Tensor] = []
                available_mask: List[bool] = []
                example_counts: Dict[str, int] = {}

                # Use the text option embedding shape as a reliable fallback vector shape.
                text_emb = self.option_embeddings[group_name][attr_name]["embeddings"]
                fallback_zero = torch.zeros_like(text_emb[0:1])

                for option in options:
                    image_paths = collect_example_images_for_option(
                        example_analysis_root=self.example_analysis_root,
                        group=group_name,
                        attribute=attr_name,
                        option=option,
                    )

                    embs: List[torch.Tensor] = []

                    for image_path in image_paths:
                        try:
                            with Image.open(image_path) as source:
                                image = source.convert("RGB")
                        except Exception as exc:
                            raise RuntimeError(
                                f"Unreadable Person D example image: {image_path}"
                            ) from exc
                        embs.append(self.model.encode_image(image))

                    if embs:
                        stacked = torch.cat(embs, dim=0)
                        prototype = stacked.mean(dim=0, keepdim=True)
                        prototype = F.normalize(prototype, dim=-1)
                        option_prototypes.append(prototype)
                        available_mask.append(True)
                    else:
                        # Keep tensor shape aligned with options. This option receives no example boost.
                        option_prototypes.append(fallback_zero)
                        available_mask.append(False)

                    example_counts[option] = len(embs)

                prototype_emb = torch.cat(option_prototypes, dim=0)
                mask_tensor = torch.tensor(
                    available_mask,
                    dtype=torch.bool,
                    device=prototype_emb.device,
                )

                cache[group_name][attr_name] = {
                    "options": options,
                    "embeddings": prototype_emb,
                    "available_mask": mask_tensor,
                    "counts": example_counts,
                }

        return cache

    def _build_example_metadata(self) -> Dict[str, Any]:
        if not self.use_example_prototypes or self.example_score_weight <= 0:
            return {"enabled": False}

        metadata: Dict[str, Any] = {
            "enabled": True,
            "readable_example_images": 0,
            "options_without_examples": [],
        }

        for group_name, attrs in self.vocabulary.attributes.items():
            for attr_name, options in attrs.items():
                counts = self.example_prototypes[group_name][attr_name]["counts"]
                for option in options:
                    count = int(counts.get(option, 0))
                    metadata["readable_example_images"] += count
                    if count == 0:
                        metadata["options_without_examples"].append(
                            f"{group_name}/{attr_name}/{option}"
                        )

        return metadata

    def _build_custom_prompt_embedding(self) -> Optional[torch.Tensor]:
        if not self.use_custom_text_prompt:
            return None

        if not self.custom_text_prompts:
            return None

        if self.text_score_weight <= 0:
            return None

        all_chunks: List[str] = []

        for prompt in self.custom_text_prompts:
            chunks = make_free_text_prompt_chunks(self.model, prompt, self.settings)
            all_chunks.extend(chunks)

        if not all_chunks:
            return None

        prompt_embs = self.model.encode_texts(all_chunks)
        prompt_emb = prompt_embs.mean(dim=0, keepdim=True)
        prompt_emb = F.normalize(prompt_emb, dim=-1)

        return prompt_emb

    @torch.no_grad()
    def predict_one(self, image: Image.Image) -> Dict[str, Dict[str, Any]]:
        image_emb = self.model.encode_image(image)
        prompt_emb = self.custom_prompt_embedding

        result: Dict[str, Dict[str, Any]] = {}

        for group_name, attrs in self.vocabulary.attributes.items():
            result[group_name] = {}

            for attr_name in attrs.keys():
                option_info = self.option_embeddings[group_name][attr_name]
                options = option_info["options"]
                option_emb = option_info["embeddings"]

                # 1) Image-to-text-option similarity.
                image_option_text_scores = image_emb @ option_emb.T
                image_option_text_scores = image_option_text_scores.squeeze(0)

                scores = self.image_score_weight * image_option_text_scores

                # 2) Example prototype similarity.
                example_info = self.example_prototypes.get(group_name, {}).get(attr_name)

                if (
                    self.use_example_prototypes
                    and self.example_score_weight > 0
                    and example_info is not None
                    and example_info.get("embeddings") is not None
                ):
                    example_emb = example_info["embeddings"]
                    example_available_mask = example_info["available_mask"].to(example_emb.device)

                    raw_example_scores = image_emb @ example_emb.T
                    raw_example_scores = raw_example_scores.squeeze(0)

                    # Missing/empty example folders receive no example boost.
                    zero_scores = torch.zeros_like(raw_example_scores)
                    example_scores = torch.where(
                        example_available_mask,
                        raw_example_scores,
                        zero_scores,
                    )

                    scores = scores + self.example_score_weight * example_scores

                # 3) Custom text prompt prior.
                if prompt_emb is not None and self.text_score_weight > 0:
                    text_scores = prompt_emb @ option_emb.T
                    text_scores = text_scores.squeeze(0)
                    scores = scores + self.text_score_weight * text_scores

                scores_cpu = scores.detach().cpu()

                if attr_name in self.vocabulary.multi_select_attributes:
                    pred = self._predict_multi(options, scores_cpu)
                else:
                    pred = self._predict_single(options, scores_cpu)

                result[group_name][attr_name] = {
                    "prediction": pred,
                    "scores": {
                        option: float(score)
                        for option, score in zip(options, scores_cpu.tolist())
                    },
                }

        return result

    def _predict_single(self, options: List[str], scores: torch.Tensor) -> str:
        idx = int(torch.argmax(scores).item())
        return options[idx]

    def _predict_multi(self, options: List[str], scores: torch.Tensor) -> List[str]:
        max_score = float(torch.max(scores).item())

        selected = [
            option
            for option, score in zip(options, scores.tolist())
            if score >= max_score - self.settings.multi_select_margin
        ]

        if len(selected) > 1 and "N/A" in selected:
            selected = [x for x in selected if x != "N/A"]

        return selected


# ============================================================
# Consistency Matching
# ============================================================

def get_consistent_labels(
    vocabulary: Vocabulary,
    plip_pred: Dict[str, Dict[str, Any]],
    conch_pred: Dict[str, Dict[str, Any]],
    copy_na_labels: bool,
) -> Dict[str, Dict[str, List[str]]]:
    consistent: Dict[str, Dict[str, List[str]]] = {}

    for group_name, attrs in vocabulary.attributes.items():
        consistent[group_name] = {}

        for attr_name in attrs.keys():
            p = plip_pred[group_name][attr_name]["prediction"]
            c = conch_pred[group_name][attr_name]["prediction"]

            if attr_name in vocabulary.multi_select_attributes:
                p_set = set(p)
                c_set = set(c)
                agreed = sorted(list(p_set & c_set))
            else:
                agreed = [p] if p == c else []

            if not copy_na_labels:
                agreed = [x for x in agreed if x != "N/A"]

            consistent[group_name][attr_name] = agreed

    return consistent


# ============================================================
# WLW extractor
# ============================================================

def verify_sha256(path: Path, expected: Optional[str], label: str) -> None:
    """Fail on a configured SHA-256 mismatch; ``None`` leaves the file unverified."""

    if expected is None:
        return
    if not path.is_file():
        raise FileNotFoundError(f"{label} file does not exist: {path}")
    check_digest(file_sha256(path), expected, label)


def verify_example_tree(
    example_dir: Path, expected: str, attributes: Mapping[str, Mapping[str, List[str]]]
) -> Dict[str, int]:
    """Fail when the few-shot tree differs from its tree hash or holds a file the loader ignores."""

    count, actual = tree_sha256(example_dir)
    check_digest(actual, expected, f"Person D example tree ({count} files)")
    count, usable = validate_example_layout(example_dir, attributes)
    return {"file_count": count, "usable_file_count": usable}


class VisualAttributeExtractor:
    """PLIP and CONCH classifiers plus their agreement for one ROI image."""

    def __init__(
        self,
        vocabulary: Vocabulary,
        settings: ExtractionSettings,
        classifiers: Mapping[str, AttributeClassifier],
    ):
        self.vocabulary = vocabulary
        self.settings = settings
        self.classifiers = dict(classifiers)
        self.example_tree: Optional[Dict[str, int]] = None

    def extract(self, image: Image.Image) -> Dict[str, Any]:
        predictions = {
            name: self.classifiers[name].predict_one(image) for name in MODEL_NAMES
        }
        return {
            "consistent": get_consistent_labels(
                self.vocabulary,
                predictions["PLIP"],
                predictions["CONCH"],
                self.settings.copy_na_labels,
            ),
            "models": predictions,
        }

    def example_metadata(self) -> Dict[str, Any]:
        return {
            name: classifier.example_metadata
            for name, classifier in self.classifiers.items()
        }


def load_prompt_document(config: Mapping[str, Any]) -> tuple[Path, Dict[str, Any]]:
    expected = required_digest(dict(config), "prompts_sha256", "extraction")
    path = resolve_person_reference_path("person_d", config["prompts_path"])
    if not path.is_file():
        raise FileNotFoundError(f"Person D prompt asset does not exist: {path}")
    raw = path.read_bytes()
    check_digest(hashlib.sha256(raw).hexdigest(), expected, "Person D prompt asset")
    return path, json.loads(raw.decode("utf-8"))


def extraction_provenance(config: Mapping[str, Any], device: str) -> Dict[str, Any]:
    """Describe the configured extraction assets without loading any model."""

    prompts_path, prompts = load_prompt_document(config)
    settings = ExtractionSettings.from_config(config)
    plip_path = resolve_person_reference_path("person_d", config["plip"]["weight_path"])
    conch_path = resolve_person_reference_path(
        "person_d", config["conch"]["checkpoint_path"]
    )
    provenance: Dict[str, Any] = {
        "backend": "plip+conch",
        "device": device,
        "prompts": {
            "path": sibling_logical_path(prompts_path),
            "version": prompts.get("version"),
            "sha256": config["prompts_sha256"],
        },
        "PLIP": {
            "weight_path": sibling_logical_path(plip_path),
            "revision": config["plip"]["revision"],
            "sha256": config["plip"]["sha256"],
            "support_files_sha256": dict(
                required_digests(
                    dict(config["plip"]), "support_files_sha256", PLIP_SUPPORT_FILES, "extraction.plip"
                )
            ),
        },
        "CONCH": {
            "model_name": config["conch"]["model_name"],
            "checkpoint_path": sibling_logical_path(conch_path),
            "revision": config["conch"]["revision"],
            "sha256": config["conch"]["sha256"],
        },
        "settings": dict(vars(settings)),
    }
    if settings.use_example_prototypes:
        example_dir = resolve_person_reference_path("person_d", config["example_dir"])
        provenance["example_dir"] = sibling_logical_path(example_dir)
        provenance["example_tree_sha256"] = required_digest(
            dict(config), "example_tree_sha256", "extraction"
        )
    return provenance


def load_extractor(config: Mapping[str, Any], device: str) -> VisualAttributeExtractor:
    """Load PLIP and CONCH from reference/person_d and build both classifiers."""

    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"Person D config requests {device!r} but CUDA is not available")

    _, prompts = load_prompt_document(config)
    vocabulary = load_vocabulary(prompts)
    settings = ExtractionSettings.from_config(config)

    plip_path = resolve_person_reference_path("person_d", config["plip"]["weight_path"])
    conch_path = resolve_person_reference_path(
        "person_d", config["conch"]["checkpoint_path"]
    )
    if not plip_path.is_dir():
        raise FileNotFoundError(f"PLIP weight directory does not exist: {plip_path}")
    if not conch_path.is_file():
        raise FileNotFoundError(f"CONCH checkpoint does not exist: {conch_path}")
    # CONCH loads its checkpoint with strict=False, so a wrong file would load silently.
    verify_sha256(plip_path / "pytorch_model.bin", config["plip"]["sha256"], "PLIP weight")
    support_files = required_digests(
        dict(config["plip"]), "support_files_sha256", PLIP_SUPPORT_FILES, "extraction.plip"
    )
    for name, digest in support_files.items():
        verify_sha256(plip_path / name, digest, f"PLIP {name}")
    verify_sha256(conch_path, config["conch"]["sha256"], "CONCH weight")

    example_dir: Optional[Path] = None
    example_tree: Optional[Dict[str, int]] = None
    if settings.use_example_prototypes:
        example_dir = resolve_person_reference_path("person_d", config["example_dir"])
        if not example_dir.is_dir():
            raise FileNotFoundError(f"Person D example directory does not exist: {example_dir}")
        example_tree = verify_example_tree(
            example_dir,
            required_digest(dict(config), "example_tree_sha256", "extraction"),
            vocabulary.attributes,
        )

    wrappers = {
        "PLIP": PLIPZeroShot(plip_path, device),
        "CONCH": CONCHZeroShot(config["conch"]["model_name"], conch_path, device),
    }
    classifiers = {
        name: AttributeClassifier(
            wrappers[name],
            vocabulary=vocabulary,
            settings=settings,
            option_prompt_template=prompts["models"][name]["option_prompt_template"],
            custom_text_prompts=prompts["models"][name]["custom_text_prompts"],
            example_dir=example_dir,
        )
        for name in MODEL_NAMES
    }
    extractor = VisualAttributeExtractor(vocabulary, settings, classifiers)
    extractor.example_tree = example_tree
    return extractor
