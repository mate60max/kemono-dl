FROM python:3.8

# Install dependencies

RUN pip install --no-cache \
    tqdm \
    requests

COPY kemono.py /usr/local/bin/kemono
RUN chmod +x /usr/local/bin/kemono

VOLUME [ "/opt/kemono" ]
WORKDIR /opt/kemono
CMD [ "kemono", "wait" ]