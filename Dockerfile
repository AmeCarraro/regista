# Build from this folder: docker build -t regista .
# Two stages. "base" holds the libraries, which change rarely; the last one adds the code and the
# page, so a change to the code rebuilds in seconds. The page is built before (run.ps1 does it):
# the image needs no Node.js, and the folder another PC installs from has the page built already. The model that reads pictures is
# not in here: it is the phone's, kept in models\phone on the PC and mounted read-only (compose.yaml).
FROM python:3.12-slim AS base
WORKDIR /build
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM base
WORKDIR /app
# Small libraries added after the first version go here, so that the large layers above are
# not downloaded again: segno draws the QR code that lets a phone in.
RUN pip install --no-cache-dir "segno>=1.6,<2"
# the cities of the world with their position (GeoNames, CC BY 4.0): what turns the position of a picture into a place
COPY data/geonames ./geonames
COPY app/ .
COPY web/dist ./static
# the index of the pictures lives in a volume mounted here, written by the app's own user
RUN mkdir -p /data && chown 1000:1000 /data
ENV HOME=/tmp PHOTOS_DIR=/photos INDEX_DIR=/data PHONE_MODELS=/models/phone
USER 1000
# 8000 is this computer's door, 8443 the encrypted one for the phones
EXPOSE 8000 8443
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
