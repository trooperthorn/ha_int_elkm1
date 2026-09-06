#!/usr/bin/with-contenv bashio
# Starts the programmer service in app mode. Everything the service needs
# arrives as environment variables; nothing secret is among them.

export ELK_PROGRAMMER_MODE="app"
export ELK_PROGRAMMER_DATA="/data"
export ELK_PROGRAMMER_HOST="$(bashio::config 'host')"
export ELK_PROGRAMMER_PORT="$(bashio::config 'port')"
export ELK_PROGRAMMER_ALLOWED_USERS="$(bashio::config 'allowed_users' | tr '\n' ',')"
export ELK_PROGRAMMER_IDLE_MINUTES="$(bashio::config 'idle_minutes')"
export ELK_PROGRAMMER_READ_ONLY="$(bashio::config 'read_only')"

if [ -z "${ELK_PROGRAMMER_ALLOWED_USERS//,/}" ]; then
  bashio::log.warning "allowed_users is empty: every request will be refused until a Home Assistant user id is listed"
fi

bashio::log.info "Elk Programmer starting on ingress port 8099 (read_only=${ELK_PROGRAMMER_READ_ONLY}, idle stop after ${ELK_PROGRAMMER_IDLE_MINUTES} min)"
exec /opt/elk/bin/python -m uvicorn elk_programmer.web.app:app --host 0.0.0.0 --port 8099 --proxy-headers
