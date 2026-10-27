FROM python:3.10.16-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libopenslide0 && rm -rf /var/lib/apt/lists/*
COPY components/person_c/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
      torch==2.6.0+cu118 --index-url https://download.pytorch.org/whl/cu118 \
      --extra-index-url https://pypi.org/simple \
    && pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
      -r /tmp/requirements.txt
COPY contracts /app/contracts
COPY components/person_c/__init__.py components/person_c/interest_pattern.py components/person_c/wsi_processing.py /app/components/person_c/
COPY components/person_c/configs /app/components/person_c/configs
COPY components/person_c/model/MRCPS_inference_model.py components/person_c/model/model_segformer.py components/person_c/model/model_resnest.py /app/components/person_c/model/
RUN touch /app/components/__init__.py
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "components.person_c.interest_pattern"]
