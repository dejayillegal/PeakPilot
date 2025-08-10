FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV UPLOAD_ROOT=/mnt/data/sessions
RUN mkdir -p /mnt/data/sessions && chmod -R 777 /mnt/data

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 7860
CMD ["gunicorn","-w","2","-k","gthread","-t","300","-b","0.0.0.0:7860","app.__init__:create_app()"]
