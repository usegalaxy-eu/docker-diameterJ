FROM ubuntu:22.04

ARG FIJI_URL=https://downloads.imagej.net/fiji/Life-Line/fiji-linux64-20170530.zip
ARG FIJI_SHA256=c776f71da8f90afb2632094076773a150bf3af6a8aa0a1b8b2a740c0b640e801
ARG DIAMETERJ_URL=https://imagej.net/imagej-wiki-static/images/6/65/DiameterJ_Fiji_-_1-018.zip
ARG DIAMETERJ_SHA256=901f20f695ab1a43104b4c4a7ae2b1bfe7bb0fd2ac6c37858fe5878299fcd3d8
ARG AUTO_THRESHOLD_URL=https://maven.scijava.org/content/groups/public/sc/fiji/Auto_Threshold/1.18.0/Auto_Threshold-1.18.0.jar
ARG AUTO_THRESHOLD_SHA256=cd13304b65d5451bf873c3263b74e71736ee0d32cfe4a848732857bd1bb5c606

ENV DEBIAN_FRONTEND=noninteractive \
    ANALYSIS_RESULTS_DIR=/app/results \
    DIAMETERJ_TIMEOUT_SECONDS=600 \
    DISPLAY=:99

# Xvfb requires this directory to exist with standard X11 permissions when the
# container is subsequently run under Galaxy's non-root UID.
RUN mkdir -p /tmp/.X11-unix \
    && chown root:root /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix

# Fiji's May-2017 ImageJ 1.51n build bundles its required Java 8 runtime. These
# packages provide the native GUI libraries and a virtual X server.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gosu \
        libasound2 \
        libfreetype6 \
        libxi6 \
        libxrender1 \
        libxt6 \
        libxtst6 \
        python3 \
        python3-pip \
        python3-venv \
        unzip \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -r /app/requirements.txt

# Download the exact Fiji and DiameterJ releases used by this workflow. Hash
# checks make the build fail if either historical artifact changes upstream.
RUN mkdir -p /app/packages/fiji-2017 /tmp/diameterj-download \
    && curl --fail --location --retry 3 \
        --output /tmp/diameterj-download/fiji.zip "$FIJI_URL" \
    && echo "$FIJI_SHA256  /tmp/diameterj-download/fiji.zip" | sha256sum --check - \
    && unzip -q /tmp/diameterj-download/fiji.zip -d /app/packages/fiji-2017 \
    && curl --fail --location --retry 3 \
        --output /tmp/diameterj-download/diameterj.zip "$DIAMETERJ_URL" \
    && echo "$DIAMETERJ_SHA256  /tmp/diameterj-download/diameterj.zip" | sha256sum --check - \
    && unzip -q /tmp/diameterj-download/diameterj.zip \
        -d /app/packages/fiji-2017/Fiji.app/plugins \
    && curl --fail --location --retry 3 \
        --output /tmp/diameterj-download/Auto_Threshold-1.18.0.jar "$AUTO_THRESHOLD_URL" \
    && echo "$AUTO_THRESHOLD_SHA256  /tmp/diameterj-download/Auto_Threshold-1.18.0.jar" | sha256sum --check - \
    && rm -f /app/packages/fiji-2017/Fiji.app/plugins/Auto_Threshold-*.jar \
    && mv /tmp/diameterj-download/Auto_Threshold-1.18.0.jar \
        /app/packages/fiji-2017/Fiji.app/plugins/ \
    && test -f /app/packages/fiji-2017/Fiji.app/jars/ij-1.51n.jar \
    && test -f /app/packages/fiji-2017/Fiji.app/plugins/AnalyzeSkeleton_-3.1.2.jar \
    && test -f /app/packages/fiji-2017/Fiji.app/plugins/DiameterJ/DiameterJ_1-018.ijm \
    && test -f /app/packages/fiji-2017/Fiji.app/plugins/DiameterJ/DiameterJ_Segment.ijm \
    && test -f /app/packages/fiji-2017/Fiji.app/plugins/Auto_Threshold-1.18.0.jar \
    && rm -rf /tmp/diameterj-download

COPY src /app/src
COPY entrypoint.sh /usr/local/bin/sem-analysis

RUN chmod 0755 \
    /usr/local/bin/sem-analysis \
    /app/src/analyze_sem.py \
    /app/src/run_diameterj_batch.py \
    /app/packages/fiji-2017/Fiji.app/ImageJ-linux64

ENTRYPOINT ["/usr/local/bin/sem-analysis"]
CMD ["--help"]
