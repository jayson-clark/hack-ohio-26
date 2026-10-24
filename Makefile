# Load .env (if present) and export its variables to every command.
-include .env
export

.PHONY: install engine web app dev types test board clean distclean

install:
	cd engine && uv sync
	cd app && pnpm install

# Python engine (WebSocket server on ws://localhost:8765)
engine:
	cd engine && uv run server.py

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

# Local agent board on http://localhost:8790 (the team board is https://hack.apps.jaysonc.dev)
board:
	python3 tools/agent_board/server.py

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
	rm -rf app/node_modules engine/.venv
