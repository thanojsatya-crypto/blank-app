#!/usr/bin/env sh
set -eu
case "${1:-}" in
  key) exec streamlit run key_generator.py --server.address=127.0.0.1 --server.port=8501 ;;
  communication) exec streamlit run communication_base_station.py --server.address=127.0.0.1 --server.port=8502 ;;
  *) echo "Usage: $0 {key|communication}" >&2; exit 2 ;;
esac
