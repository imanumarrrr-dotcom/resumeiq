FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m appuser && mkdir -p /data/uploads && chown -R appuser /data /app
USER appuser
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/login')"
CMD ["gunicorn", "-w", "2", "--threads", "4", "-b", "0.0.0.0:8000", "app:app"]
