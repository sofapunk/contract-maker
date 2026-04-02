FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY templates/ ./templates/
ENV GOOGLE_SERVICE_ACCOUNT_PATH=/app/.secrets/creative-strategy-clode-f15c21f08fd2.json
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
