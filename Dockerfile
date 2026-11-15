FROM --platform=linux/arm64 python:3.12.12-slim AS builder
WORKDIR /app
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM --platform=linux/arm64 python:3.12.12-slim
RUN useradd -r -u 1001 appuser
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY main.py agent.py policies.py shop.py tools_client.py orders.json ./
ENV PATH="/app/.venv/bin:$PATH" \
    DOCKER_CONTAINER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_OBSERVABILITY_ENABLED=true \
    OTEL_PYTHON_DISTRO=aws_distro \
    OTEL_PYTHON_CONFIGURATOR=aws_configurator \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
    UNIFIED_TRACES_DESTINATION_ENABLED=true \
    AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT=true
USER appuser
EXPOSE 8080
CMD ["opentelemetry-instrument", "python", "main.py"]
