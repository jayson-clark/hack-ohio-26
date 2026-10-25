# The agent board: stdlib Python serving the API and the prebuilt web UI (web/dist).
#   docker build -t agent-board tools/agent_board
#   docker run -p 8790:8790 -v board-data:/data -e BOARD_TOKEN=... agent-board
# Put it behind a TLS proxy that doesn't buffer /api/events (SSE).
FROM python:3.12-slim
WORKDIR /board
COPY server.py board.py ./
COPY boardsrv ./boardsrv
COPY web/dist ./web/dist
ENV BOARD_HOST=0.0.0.0 BOARD_PORT=8790 BOARD_DB=/data/board.db PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8790
HEALTHCHECK CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/api/health', timeout=3)"
CMD ["python3", "server.py"]
