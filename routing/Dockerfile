# syntax=docker/dockerfile:1.7
# Routing service of MyGPXContainer: GraphHopper with the map regions MGC
# asks for (run.py builds and serves the graph). Only in the Docker network.
FROM eclipse-temurin:21-jre
ARG GH_VERSION=11.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends osmium-tool python3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && mkdir -m 755 /app
ADD --chmod=644 --checksum=sha256:8462f758d9ea49edaded557cec5c687a0a24f004ec371cd4daaeb0534824ea33 \
    https://github.com/graphhopper/graphhopper/releases/download/11.1/graphhopper-web-11.1.jar \
    /app/graphhopper.jar
COPY config.yml run.py /app/
COPY models /app/models
# uid 1000 like MGC's app user: both write to the shared volume
RUN if id -u 1000 >/dev/null 2>&1; then userdel -r "$(id -un 1000)"; fi \
    && useradd -u 1000 -m routing && mkdir -p /data && chown routing:routing /data
# TZ (e.g. Europe/Berlin) from the compose file: monthly rebuilds run at night
ENV PYTHONUNBUFFERED=1
USER routing
WORKDIR /data
EXPOSE 8989
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD python3 -c "import json,sys; sys.exit(json.load(open('/data/status.json'))['state'] == 'failed')"
CMD ["python3", "/app/run.py"]
