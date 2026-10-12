# Build from this folder: docker build -t regista .
# Three stages. "web" builds the page. "base" holds what is large and changes rarely:
# PyTorch, the libraries and the model that reads pictures. The last one adds the code,
# so a change to the code rebuilds in seconds.
FROM node:24-alpine AS web
WORKDIR /web
# Dependencies first: this layer is cached until the lock file changes
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ .
RUN npm run build


FROM python:3.12-slim AS base
WORKDIR /build
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1
# where the model that reads pictures is kept, readable by the user the app runs as
ENV PYTHONUNBUFFERED=1 HF_HOME=/opt/models
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# The model is downloaded here, once, at build time: the app then starts without the internet
RUN python -c "import open_clip; open_clip.create_model_and_transforms('ViT-B-32-quickgelu', pretrained='openai')" \
    && chmod -R a+rX /opt/models


FROM base
WORKDIR /app
# Small libraries added after the first version go here, so that the large layers above are
# not downloaded again: segno draws the QR code that lets a phone in.
RUN pip install --no-cache-dir "segno>=1.6,<2"
# the cities of the world with their position (GeoNames, CC BY 4.0): what turns the position of a picture into a place
COPY data/geonames ./geonames
COPY app/ .
COPY --from=web /web/dist ./static
# the index of the pictures lives in a volume mounted here, written by the app's own user
RUN mkdir -p /data && chown 1000:1000 /data
ENV HF_HUB_OFFLINE=1 HOME=/tmp PHOTOS_DIR=/photos INDEX_DIR=/data
USER 1000
# 8000 is this computer's door, 8443 the encrypted one for the phones
EXPOSE 8000 8443
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
