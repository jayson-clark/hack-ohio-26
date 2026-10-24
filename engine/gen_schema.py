"""Print the protocol's JSON schema to stdout. Used by `make types`."""

import json

from protocol import Protocol

schema = Protocol.model_json_schema(mode="serialization")

# Property titles make json2ts emit an alias per field (X1, Type3, ...).
# Drop them so fields inline, and name the two unions explicitly.
for model in [schema, *schema["$defs"].values()]:
    for prop in model.get("properties", {}).values():
        prop.pop("title", None)
schema["properties"]["engine"]["title"] = "EngineMessage"
schema["properties"]["client"]["title"] = "ClientMessage"

print(json.dumps(schema, indent=2))
