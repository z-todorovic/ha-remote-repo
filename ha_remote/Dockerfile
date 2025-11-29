FROM python:3.11-alpine
RUN apk add --no-cache jq && pip install --no-cache-dir requests
COPY ha_remote_relay.py /ha_remote_relay.py
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
