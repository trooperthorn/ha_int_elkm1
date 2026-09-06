#!/usr/bin/with-contenv bashio
# Starts the programmer service in app mode. Everything the service needs
# arrives as environment variables; nothing secret is among them.

export ELK_PROGRAMMER_MODE="app"
export ELK_PROGRAMMER_DATA="/data"
export ELK_PROGRAMMER_CONNECTION="$(bashio::config 'connection')"
if bashio::config.has_value 'serial_port'; then
  export ELK_PROGRAMMER_SERIAL_PORT="$(bashio::config 'serial_port')"
fi
export ELK_PROGRAMMER_BAUD="$(bashio::config 'baud')"
if bashio::config.has_value 'host'; then
  export ELK_PROGRAMMER_HOST="$(bashio::config 'host')"
fi
export ELK_PROGRAMMER_PORT="$(bashio::config 'port')"
export ELK_PROGRAMMER_RELEASE_INTEGRATION="$(bashio::config 'release_integration')"
export ELK_PROGRAMMER_ALLOWED_USERS="$(bashio::config 'allowed_users' | tr '\n' ',')"
export ELK_PROGRAMMER_IDLE_MINUTES="$(bashio::config 'idle_minutes')"
export ELK_PROGRAMMER_READ_ONLY="$(bashio::config 'read_only')"

if [ -z "${ELK_PROGRAMMER_ALLOWED_USERS//,/}" ]; then
  bashio::log.warning "allowed_users is empty: every request will be refused until a Home Assistant user id is listed"
fi

if [ "${ELK_PROGRAMMER_CONNECTION}" = "serial" ] && [ -z "${ELK_PROGRAMMER_SERIAL_PORT:-}" ]; then
  bashio::log.warning "connection is serial but no serial_port is chosen; pick one in the app configuration"
fi

bashio::log.info "Elk Programmer starting on ingress port 8099 (read_only=${ELK_PROGRAMMER_READ_ONLY}, idle stop after ${ELK_PROGRAMMER_IDLE_MINUTES} min)"
exec /opt/elk/bin/python -m uvicorn elk_programmer.web.app:app --host 0.0.0.0 --port 8099 --proxy-headers
