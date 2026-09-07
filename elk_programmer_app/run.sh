#!/usr/bin/with-contenv bashio
# Starts the programmer service in app mode. Everything the service needs
# arrives as environment variables; nothing secret is among them. Each
# variable is assigned first and exported second so a failing command
# substitution is not masked by the export (ShellCheck SC2155).

ELK_PROGRAMMER_MODE="app"
ELK_PROGRAMMER_DATA="/data"
ELK_PROGRAMMER_CONNECTION="$(bashio::config 'connection')"
ELK_PROGRAMMER_BAUD="$(bashio::config 'baud')"
ELK_PROGRAMMER_PORT="$(bashio::config 'port')"
ELK_PROGRAMMER_RELEASE_INTEGRATION="$(bashio::config 'release_integration')"
ELK_PROGRAMMER_FORWARD_AUDIT="$(bashio::config 'forward_audit')"
ELK_PROGRAMMER_ALLOWED_USERS="$(bashio::config 'allowed_users' | tr '
' ',')"
ELK_PROGRAMMER_IDLE_MINUTES="$(bashio::config 'idle_minutes')"
ELK_PROGRAMMER_READ_ONLY="$(bashio::config 'read_only')"
export ELK_PROGRAMMER_MODE ELK_PROGRAMMER_DATA ELK_PROGRAMMER_CONNECTION ELK_PROGRAMMER_BAUD   ELK_PROGRAMMER_PORT ELK_PROGRAMMER_RELEASE_INTEGRATION ELK_PROGRAMMER_FORWARD_AUDIT ELK_PROGRAMMER_ALLOWED_USERS   ELK_PROGRAMMER_IDLE_MINUTES ELK_PROGRAMMER_READ_ONLY

if bashio::config.has_value 'serial_port'; then
  ELK_PROGRAMMER_SERIAL_PORT="$(bashio::config 'serial_port')"
  export ELK_PROGRAMMER_SERIAL_PORT
fi
if bashio::config.has_value 'host'; then
  ELK_PROGRAMMER_HOST="$(bashio::config 'host')"
  export ELK_PROGRAMMER_HOST
fi

if [ -z "${ELK_PROGRAMMER_ALLOWED_USERS//,/}" ]; then
  bashio::log.warning "allowed_users is empty: every request will be refused until a Home Assistant user id is listed"
fi
if [ "${ELK_PROGRAMMER_CONNECTION}" = "serial" ] && [ -z "${ELK_PROGRAMMER_SERIAL_PORT:-}" ]; then
  bashio::log.warning "connection is serial but no serial_port is chosen; pick one in the app configuration"
fi

bashio::log.info "Elk Programmer starting on ingress port 8099 (connection=${ELK_PROGRAMMER_CONNECTION}, read_only=${ELK_PROGRAMMER_READ_ONLY}, idle stop after ${ELK_PROGRAMMER_IDLE_MINUTES} min)"
exec /opt/elk/bin/python -m uvicorn elk_programmer.web.app:app --host 0.0.0.0 --port 8099 --proxy-headers
