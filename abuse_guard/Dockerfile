FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /service

COPY abuse_guard/requirements.txt /service/requirements.txt

RUN pip install --no-cache-dir -r /service/requirements.txt

COPY abuse_guard /service/abuse_guard

ENV PYTHONPATH=/service

EXPOSE 8000

CMD ["sh", "-c", "python -m abuse_guard"]
