FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04 AS runtime

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       git libopenslide0=3.4.1+dfsg-5build1 python3 python3-pip python-is-python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Ubuntu's pip 22.0.2 builds CONCH's PEP 621 metadata with project name "unknown".
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check pip==25.2
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check \
      torch==2.11.0+cu128 torchvision==0.26.0+cu128 \
      --index-url https://download.pytorch.org/whl/cu128
COPY components/person_d/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check \
      -r /tmp/requirements.txt
COPY contracts /app/contracts
# Runtime files only: the tests and the examples (with the synthetic TIFF) are in the test target.
COPY components/person_d/*.py components/person_d/*.json components/person_d/component.yaml \
     /app/components/person_d/
COPY components/person_d/configs /app/components/person_d/configs
RUN touch /app/components/__init__.py
# torch derives the default inductor cache from the user name, which fails for a UID without a
# passwd entry (integration/compose.yaml runs as LOCAL_UID). torch only creates this empty
# directory below run/cache/person_d; nothing is compiled, so no cache files are written.
ENV PYTHONPATH=/app \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCHINDUCTOR_CACHE_DIR=/run/cache/person_d/torchinductor
ENTRYPOINT ["python3", "-m", "components.person_d.visual_filter"]

# docker build --target test: the runtime image plus the tests, the examples and the mapping
# document that tests/test_mapping.py compares with mapping_acceptance.json.
FROM runtime AS test
COPY components/person_d/tests /app/components/person_d/tests
COPY components/person_d/examples /app/components/person_d/examples
COPY components/person_d/MAPPING.md /app/components/person_d/MAPPING.md

FROM runtime
