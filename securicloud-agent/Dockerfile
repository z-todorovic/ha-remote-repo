FROM python:3.11-alpine
RUN apk add --no-cache jq && pip install --no-cache-dir requests
COPY securicloud_agent.py /securicloud_agent.py
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
