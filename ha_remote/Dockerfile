FROM python:3.11-alpine
RUN pip install --no-cache-dir websockets requests

# Copy everything in this folder
COPY . /data/

# Move run.sh to root
RUN mv /data/run.sh /run.sh && chmod +x /run.sh

CMD ["/run.sh"]
