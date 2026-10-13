FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home challenge \
    && mkdir /data && chown challenge:challenge /data
COPY challenge ./challenge
COPY static ./static
COPY data/image.png ./data/image.png
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3).read()"
ENTRYPOINT ["python", "-m", "challenge.server", "--data", "/data"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
