FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./backend/app
COPY supabase ./supabase
WORKDIR /srv/backend

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# O mesmo container roda a API (padrão) ou o worker: `python -m app.cli worker`
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
