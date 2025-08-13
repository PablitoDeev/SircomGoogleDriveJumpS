FROM python:3.11-slim

# Evita cache y genera logs en stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Instalar dependencias del sistema si hace falta (ejemplo: gcc, libmagic, etc.)
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del proyecto
COPY . .

# Expone puerto interno
EXPOSE 5000

# Usuario no-root por seguridad
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Arranque con gunicorn (2 workers para peticiones concurrentes)
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "jumpsellersircomform:app"]
