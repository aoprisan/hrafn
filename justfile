version := `python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])'`

# Run the envelope.py test suite (stdlib only).
test:
    python3 -m unittest -v

# Validate the plugin manifest and the marketplace manifest.
validate:
    claude plugin validate .

# Build dist/hrafn-<version>.zip from tracked files only (no caches, no local config).
zip:
    mkdir -p dist
    git archive --format=zip --prefix=hrafn/ -o dist/hrafn-{{version}}.zip HEAD
    @echo "dist/hrafn-{{version}}.zip"
