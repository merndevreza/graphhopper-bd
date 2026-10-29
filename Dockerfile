# GraphHopper routing service, pinned to the official release JAR.
# (The GraphHopper project no longer publishes official Docker images, so we
# wrap the release JAR ourselves — same result, but version-pinned.)
FROM eclipse-temurin:21-jre

# curl is used by the compose healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /graphhopper

# JAR fetched by scripts/download.sh (kept out of git); renamed for the CMD below
COPY graphhopper-web-11.1.jar graphhopper.jar

ENV JAVA_OPTS="-Xms512m -Xmx4g"

# Starts the web server; if graph-cache is empty it imports the PBF first,
# so the very first start takes 10-20 minutes and later starts are seconds.
CMD ["sh", "-c", "exec java $JAVA_OPTS -jar graphhopper.jar server config.yml"]
