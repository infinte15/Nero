# Schlank und ohne Build-Werkzeuge im Ergebnis - Nero ist reines Python.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

WORKDIR /app

# Standardmaessig nur die Grundabhaengigkeiten. Wer Whisper im Haus will, baut
# mit --build-arg NERO_EXTRAS="[stt-local]" - das zieht ctranslate2 mit und
# verdreifacht das Image, deshalb ist es nicht die Vorgabe.
ARG NERO_EXTRAS=""

COPY pyproject.toml ./
COPY nero ./nero
RUN pip install --no-cache-dir ".${NERO_EXTRAS}"

# Nicht als root. /data haelt den Nutzungszaehler und spaeter die Geraete-Tokens.
RUN useradd -r -u 1001 nero && mkdir -p /data && chown nero:nero /data
USER nero

ENV USAGE_FILE=/data/usage.json

EXPOSE 8000
CMD ["uvicorn", "nero.main:app", "--host", "0.0.0.0", "--port", "8000"]
