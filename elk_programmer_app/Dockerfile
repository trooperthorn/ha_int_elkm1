# 3.24 is a moving tag, so the digest is what the build resolves; bump tag and
# digest together (docker buildx imagetools inspect). Same base as the HA SOC probe.
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24@sha256:93ef607824e3f27e868f11b10938283a98bf880ed57bcf8eaa81c6c2d521f6f5
FROM ${BUILD_FROM}

# BUILD_VERSION comes from the Supervisor (the app's config.yaml version). The
# default source installs the programmer wheel that the release of that same
# version published, checked against the release's SHA256SUMS; CI passes
# ELK_PROGRAMMER_SOURCE=git with a commit ref to scan a pull request's image.
ARG BUILD_VERSION="0.0.0"
ARG ELK_PROGRAMMER_SOURCE="release"
ARG ELK_PROGRAMMER_REF="main"
ARG ELK_PROGRAMMER_REPO="https://github.com/trooperthorn/ha_int_elkm1"

LABEL \
  org.opencontainers.image.title="Elk Programmer" \
  org.opencontainers.image.description="Installer programming for Elk-M1 Gold panels" \
  org.opencontainers.image.source="https://github.com/trooperthorn/ha_int_elkm1" \
  org.opencontainers.image.licenses="MIT" \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}"

# apk upgrade pulls Alpine fixes published after the base digest; tempio is a Go
# binary the base ships that this app never runs, and it is what the image scan
# flags, so it is removed.
RUN set -eu; \n  apk upgrade --no-cache; \n  apk add --no-cache python3 py3-pip; \n  rm -f /usr/bin/tempio; \n  python3 -m venv /opt/elk; \
  if [ "$ELK_PROGRAMMER_SOURCE" = "release" ]; then \
    NORMALIZED="$(printf '%s' "$BUILD_VERSION" | sed -E 's/\.0+([0-9])/.\1/g')"; \
    WHEEL="elk_programmer-${NORMALIZED}-py3-none-any.whl"; \
    BASE="${ELK_PROGRAMMER_REPO}/releases/download/v${BUILD_VERSION}"; \
    mkdir -p /tmp/release && cd /tmp/release; \
    curl -fsSLO "${BASE}/${WHEEL}"; \
    curl -fsSLO "${BASE}/SHA256SUMS"; \
    grep " ${WHEEL}\$" SHA256SUMS | sha256sum -c -; \
    /opt/elk/bin/pip install --no-cache-dir "/tmp/release/${WHEEL}"; \
    cd / && rm -rf /tmp/release; \
  else \
    apk add --no-cache git; \
    /opt/elk/bin/pip install --no-cache-dir "elk-programmer @ git+${ELK_PROGRAMMER_REPO}@${ELK_PROGRAMMER_REF}"; \
    apk del git; \
  fi

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
