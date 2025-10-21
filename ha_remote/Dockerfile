
FROM python:3.11-alpine
RUN pip install --no-cache-dir websockets requests

# Work inside /data
WORKDIR /data

# Copy everything from this folder into /data
COPY . .

# List files for verification at build time
RUN echo "[DEBUG] Files in /data:" && ls -R /data

# Make sure run.sh is executable
RUN chmod +x /data/run.sh

# Start script from /data
CMD ["/bin/sh", "-c", "/data/run.sh"]
