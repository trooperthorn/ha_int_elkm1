ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

ARG BUILD_VERSION="0.0.0"
ARG ELK_PROGRAMMER_REF="main"

LABEL \
  org.opencontainers.image.title="Elk Programmer" \
  org.opencontainers.image.description="Installer programming for Elk-M1 Gold panels" \
  org.opencontainers.image.source="https://github.com/trooperthorn/ha_int_elkm1" \
  org.opencontainers.image.licenses="MIT" \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}"

RUN apk add --no-cache python3 py3-pip git \
  && python3 -m venv /opt/elk \
  && /opt/elk/bin/pip install --no-cache-dir \
       "elk-programmer @ git+https://github.com/trooperthorn/ha_int_elkm1@${ELK_PROGRAMMER_REF}" \
  && apk del git

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
