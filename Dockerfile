FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Port per spec
EXPOSE 7860
# Gunicorn per spec
CMD ["gunicorn","-w","2","-k","gthread","-t","300","-b","0.0.0.0:7860","app.__init__:create_app()"]
