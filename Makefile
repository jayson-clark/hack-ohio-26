# Load .env (if present) and export its variables to every command.
-include .env
export

.PHONY: install engine web app dev types test board board-web board-dev board-vite clean distclean

install:
	cd engine && uv sync
	cd app && pnpm install
	cd tools/agent_board/web && pnpm install

# Python engine (WebSocket server on ws://localhost:8765). ENGINE_EXTRAS in .env
# picks optional extras, e.g. "ml voice" for the fire emulator and push-to-talk.
engine:
	cd engine && uv run $(addprefix --extra ,$(ENGINE_EXTRAS)) server.py

# UI in a plain browser: open http://localhost:1420/?view=console and ?view=projector
web:
	cd app && pnpm dev

# UI in the Tauri shell
app:
	cd app && pnpm tauri dev

# Engine + Tauri app together
dev:
	$(MAKE) -j2 engine app

# Regenerate app/src/shared/protocol.ts from engine/protocol.py
types:
	(cd engine && uv run gen_schema.py) | (cd app && pnpm exec json2ts --no-additionalProperties \
		--bannerComment "/* Generated from engine/protocol.py by \`make types\`. Do not edit by hand. */") \
		> app/src/shared/protocol.ts

test:
	cd engine && uv run pytest -q
	cd app && pnpm exec tsc --noEmit
	uv run --project engine pytest -q tools/agent_board/tests
	cd tools/agent_board/web && pnpm exec tsc --noEmit

# Local agent board on http://localhost:8790 (the team board is https://hack.apps.jaysonc.dev)
board:
	python3 tools/agent_board/server.py

# Rebuild the board's web UI into tools/agent_board/web/dist (committed, so the server needs no Node)
board-web:
	cd tools/agent_board/web && pnpm install && pnpm build

# Board UI with hot reload on http://localhost:5173, against a local `make board`
board-dev:
	$(MAKE) -j2 board board-vite

board-vite:
	cd tools/agent_board/web && BOARD_URL=http://localhost:8790 pnpm dev

# Remove build output and caches. Keeps .env, the agent board's data, generated
# STL tiles and the elevation tile cache (slow to rebuild). Installed
# dependencies stay too; `make distclean` removes those.
clean:
	rm -rf app/dist app/dist-ssr app/src-tauri/target app/src-tauri/gen/schemas
	rm -rf engine/.pytest_cache
	find engine tools -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -f engine/camera-*.jpg

# Also remove installed dependencies; `make install` brings them back.
distclean: clean
	rm -rf app/node_modules engine/.venv tools/agent_board/web/node_modules
