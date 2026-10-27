ARG PERSON_A_RUNTIME_BASE=python:3.11-slim-bookworm@sha256:2fc9207f64226cb05ac317cee0bab6fa55a9ea311ce5a086baddd4b4a83c2d3c
FROM ${PERSON_A_RUNTIME_BASE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HF_HOME=/run/cache/huggingface \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Modern pip resumes interrupted HTTP downloads instead of restarting large
# CUDA wheels from byte zero.  Pin it so Docker builds remain reproducible.
RUN --mount=type=cache,id=person-a-pip-bootstrap,target=/root/.cache/pip \
    python -m pip install --disable-pip-version-check \
    --retries 20 --timeout 600 \
    --index-url https://pypi.org/simple \
    pip==26.2.1

# CUDA userspace comes from the pinned PyTorch wheel. The host supplies only
# the NVIDIA driver and Container Toolkit.
RUN --mount=type=cache,id=person-a-pytorch-cu124,target=/root/.cache/pip \
    for attempt in 1 2 3; do \
        python -m pip install --disable-pip-version-check \
            --retries 20 --timeout 600 --resume-retries 20 \
            torch==2.6.0 torchvision==0.21.0 \
            --index-url https://download.pytorch.org/whl/cu124 \
            --extra-index-url https://pypi.org/simple \
        && exit 0; \
        echo "PyTorch install failed (attempt ${attempt}/3); resuming"; \
    done; \
    exit 1

COPY components/person_a/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    grep -v '^bitsandbytes==' /tmp/requirements.txt > /tmp/requirements-runtime.txt \
    && python -m pip install --disable-pip-version-check \
    --retries 20 --timeout 600 --resume-retries 20 --prefer-binary \
    --index-url https://pypi.org/simple \
    -r /tmp/requirements-runtime.txt

# Keep the 41 MB native wheel separate so a transient or corrupted transfer
# can be retried without downloading every other runtime dependency again.
RUN --mount=type=cache,id=person-a-bitsandbytes,target=/root/.cache/pip \
    for attempt in 1 2 3; do \
        python -m pip install --disable-pip-version-check \
            --retries 20 --timeout 600 --resume-retries 20 --prefer-binary --no-deps \
            --index-url https://pypi.org/simple \
            bitsandbytes==0.50.1 \
        && exit 0; \
        echo "bitsandbytes install failed (attempt ${attempt}/3); retrying"; \
    done; \
    exit 1

COPY contracts /app/contracts
COPY components/person_a /app/components/person_a
RUN touch /app/components/__init__.py \
    && mkdir -p /run/cache/huggingface

ENTRYPOINT ["python", "-m", "components.person_a.report_decompose"]
