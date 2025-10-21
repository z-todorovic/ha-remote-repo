FROM python:3.11-alpine
RUN pip install --no-cache-dir websockets requests

# Copy all local files into the image
COPY . /data/

# Move the launcher script to root and make it executable
RUN mv /data/run.sh /run.sh && chmod +x /run.sh

CMD ["/run.sh"]
