FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.30.* prometheus-client==0.21.*
COPY app.py /app/app.py
WORKDIR /app
CMD ["uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8019", "--log-level", "warning"]
