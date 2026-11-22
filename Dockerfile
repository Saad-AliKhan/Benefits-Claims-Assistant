# One container for the whole app (for the live demo link). Build: docker build -t lastmile .
# Run:  docker run -p 8080:8080 -e SECRET_KEY=<long random> lastmile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Whisper model inside the image, so the container starts offline
ARG WHISPER_MODEL=small
ENV HF_HOME=/srv/models WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')"
COPY . .
RUN python -m scripts.make_fake_people && python -m tools.specimen_documents \
 && useradd --create-home --uid 10001 app && chown -R app /srv
USER app
ENV PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 DATABASE_URL=sqlite:////srv/data/lastmile.db
EXPOSE 8080
CMD ["sh", "-c", "python -m alembic upgrade head && python -m scripts.seed --demo-claims && uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1"]
