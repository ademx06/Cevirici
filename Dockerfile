FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8780
ENV WHISPER_MODEL=tiny
ENV DISABLE_WHISPER=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8780

CMD ["python3", "server.py"]
