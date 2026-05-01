FROM python:3.11-slim

WORKDIR /app
COPY . /app

ENV PORT=5000
EXPOSE 5000

CMD ["python", "run_local.py"]
