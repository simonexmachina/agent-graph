#!/usr/bin/env bash
set -euo pipefail

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/agentgraph-wheel-test.XXXXXX")"
server_pid=""

cleanup() {
  if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
    kill "${server_pid}"
    wait "${server_pid}" 2>/dev/null || true
  fi
  rm -rf "${work_dir}"
}
trap cleanup EXIT

repo_dir="$(pwd)"
dist_dir="${work_dir}/dist"
venv_dir="${work_dir}/venv"
config_dir="${work_dir}/config"
server_log="${work_dir}/server.log"
server_port=18765

uv build --package agentgraph-server --wheel --out-dir "${dist_dir}"
uv build --package agentgraph-connector-web --wheel --out-dir "${dist_dir}"
wheel="$(find "${dist_dir}" -maxdepth 1 -name 'agentgraph_server-*.whl' -print -quit)"
web_connector_wheel="$(find "${dist_dir}" -maxdepth 1 -name 'agentgraph_connector_web-*.whl' -print -quit)"
test -n "${wheel}"
test -n "${web_connector_wheel}"

uv venv "${venv_dir}" --python 3.12
uv pip install --python "${venv_dir}/bin/python" "${wheel}" "${web_connector_wheel}"

cd "${work_dir}"
AGENTGRAPH_CONFIG_DIR="${config_dir}" \
  "${venv_dir}/bin/agentgraph" demo add --json | grep --fixed-strings '"entities": 9'
AGENTGRAPH_CONFIG_DIR="${config_dir}" \
AGENTGRAPH_SERVER_PORT="${server_port}" \
  "${venv_dir}/bin/agentgraph" serve >"${server_log}" 2>&1 &
server_pid=$!

for _ in $(seq 1 30); do
  if curl --fail --silent "http://127.0.0.1:${server_port}/health" >/dev/null; then
    break
  fi
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    cat "${server_log}" >&2
    exit 1
  fi
  sleep 1
done

curl --fail --silent "http://127.0.0.1:${server_port}/health" | grep --fixed-strings '"status":"ok"'
curl --fail --silent "http://127.0.0.1:${server_port}/viewer" | grep --fixed-strings '<title>AgentGraph Viewer</title>'
test -s "${config_dir}/agentgraph.db"

cd "${repo_dir}"
