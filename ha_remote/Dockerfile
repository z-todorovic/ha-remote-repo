FROM python:3.11-alpine
RUN pip install --no-cache-dir websockets requests

WORKDIR /data
COPY . .

# Debug: list what was actually copied
RUN echo "[DEBUG] Listing contents of /data after COPY:" && ls -R /data

RUN chmod +x /data/run.sh
CMD ["/data/run.sh"]
