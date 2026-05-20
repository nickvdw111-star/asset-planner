FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /data is where the DB and uploads live — mount this from the host
RUN mkdir -p /data/uploads

ENV DATA_DIR=/data

EXPOSE 5050

CMD ["python", "app.py"]
