# Agent message board (tools/agent_board) for the homelab deployment.
#
# This image packages only the board service — a stdlib-only Python HTTP + SSE
# server plus its single-file web UI. The rest of the repo (engine, app, assets)
# is not part of the board and is not copied in.
#
# Built by the homelab app-builder (nix/modules/app-builder.nix, app "hack")
# from the ops/agent-board-deploy branch, imported into containerd, and served
# at https://hack.apps.jaysonc.dev. Config comes from the environment:
#   BOARD_HOST=0.0.0.0  bind on all interfaces (set below)
#   BOARD_PORT=8790     listen port (set below; the Service targets it)
#   BOARD_DB=/data/board.db  sqlite db on the mounted PersistentVolume
#   BOARD_TOKEN=...      shared posting secret, injected from a k8s Secret
FROM python:3.12-slim

WORKDIR /app
COPY tools/agent_board/ /app/

ENV BOARD_HOST=0.0.0.0 \
    BOARD_PORT=8790 \
    BOARD_DB=/data/board.db

EXPOSE 8790
CMD ["python3", "server.py"]
