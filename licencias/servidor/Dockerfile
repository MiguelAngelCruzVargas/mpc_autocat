FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY servidor.py cobro.py correo.py ./
ENV PORT=8780 LICENCIA_DB=/data/licencias.db
EXPOSE 8780
CMD ["python", "servidor.py"]
