FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY twilio_emulator ./twilio_emulator

EXPOSE 8080

CMD ["sh", "-c", "uvicorn twilio_emulator.app:create_app --factory --host 0.0.0.0 --port \"$PORT\""]