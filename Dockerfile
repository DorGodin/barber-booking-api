FROM python:3.13-slim
WORKDIR /app
RUN useradd --create-home app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app ./app
# The database lives on a volume at /data. A named volume takes its owner from
# the image the first time it is created; without this it is root's, and the
# non-root app cannot open its own database.
RUN mkdir /data && chown app /data
USER app
ENV DATABASE_URL=sqlite:////data/barber.db
EXPOSE 8100
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100", "--workers", "2"]
