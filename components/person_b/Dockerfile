FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HUB_OFFLINE=1

# Same torch wheel as person_a's image (the CUDA 12.4 userspace is inside the wheel; the host
# only supplies the NVIDIA driver and Container Toolkit, run with --gpus all). With
# embedding.device=auto it falls back to CPU when no GPU is visible.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
    --retries 10 --timeout 120 \
    torch==2.6.0 \
    --index-url https://download.pytorch.org/whl/cu124 \
    --extra-index-url https://pypi.org/simple
COPY components/person_b/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
    -r /tmp/requirements.txt

# The embedding model and the knowledge base are NOT in the image: they are mounted read-only
# under /reference/person_b/ (compose mounts ../../reference at /reference).
COPY contracts /app/contracts
COPY components/person_b /app/components/person_b
# Person B's own tests (about 40 KB; they need no model, index or corpus), so the documented
#   docker run --rm --entrypoint python <image> -m unittest tests.test_dense_retrieval tests.test_person_b_examples -v
# runs inside the image that is shipped. The other root tests belong to other components.
COPY tests/test_dense_retrieval.py tests/test_person_b_examples.py /app/tests/
RUN touch /app/components/__init__.py
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "components.person_b.knowledge_retrieval"]
