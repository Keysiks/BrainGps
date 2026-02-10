FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаём пользователя + каталоги и права (ПОКА мы root)
RUN useradd -m -u 1000 braingps \
    && mkdir -p /var/lib/braingps \
    && chown -R braingps:braingps /app /var/lib/braingps

USER braingps

CMD ["python", "main.py"]