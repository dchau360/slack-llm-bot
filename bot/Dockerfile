FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN chmod 0755 /app && chmod 0644 /app/app.py /app/requirements.txt

USER nobody

CMD ["python", "app.py"]
