"""
Resolves EVE item names to ESI type IDs using the /universe/ids/ endpoint,
which accepts a batch of names and returns matches across categories
(inventory types, systems, etc). We only care about inventory_types here.

Docs: https://esi.evetech.net/ui/#/Universe/post_universe_ids
"""
import requests

ESI_BASE = "https://esi.evetech.net/latest"
BATCH_SIZE = 500  # ESI limit per /universe/ids/ call


def resolve_names_to_ids(names: list[str]) -> dict[str, int]:
    """
    Given a list of item names, returns a dict mapping name -> type_id
    for every name ESI recognises as an inventory type. Names it doesn't
    recognise are simply absent from the result.
    """
    unique_names = list({n for n in names if n})
    if not unique_names:
        return {}

    resolved = {}
    for i in range(0, len(unique_names), BATCH_SIZE):
        batch = unique_names[i:i + BATCH_SIZE]
        try:
            resp = requests.post(f"{ESI_BASE}/universe/ids/", json=batch, timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            # ESI hiccup — skip this batch rather than failing the whole import.
            # Fits still save with unresolved type_ids (None); can be re-resolved later.
            continue

        data = resp.json()
        for entry in data.get("inventory_types", []):
            resolved[entry["name"]] = entry["id"]

    return resolved
