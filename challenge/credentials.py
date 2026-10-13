"""Organizer-side team provisioning. Restart the server after changing credentials."""
import json
import secrets
import tempfile
from pathlib import Path

from .store import ID


def add_team(root, team):
    if not isinstance(team, str) or not ID.fullmatch(team):
        raise ValueError('Team ID must contain 1–80 letters, digits, underscores, or hyphens')
    root = Path(root)
    path = root / 'config.json'
    config = json.loads(path.read_text())
    if team in config['teams']:
        raise ValueError('Team already exists; its token has not been changed')
    token = secrets.token_urlsafe(32)
    config['teams'][team] = token
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=root, delete=False) as output:
            temporary = Path(output.name)
            json.dump(config, output, indent=2)
            output.write('\n')
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return token
