FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/ygc
COPY app/pyproject.toml app/constraints.txt app/build-requirements.txt ./app/
COPY app/src ./app/src
RUN python -m pip install --no-cache-dir pip==26.2.1 && \
    python -m pip install --no-cache-dir --constraint app/constraints.txt \
    --build-constraint app/build-requirements.txt './app[postgres,identity,storage]' && \
    useradd --uid 10001 --create-home ygc
USER 10001
CMD ["python", "-m", "ygc.cloud_account_runtime"]
