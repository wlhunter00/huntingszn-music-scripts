# HuntingSzn Music Scripts — run from repo root with uv
MUSIC_ROOT ?= /Volumes/Will Hunter Music
export MUSIC_DRIVE_ROOT := $(MUSIC_ROOT)
export PYTHONPATH := $(CURDIR)

STEM_IN := $(MUSIC_ROOT)/Stem Splitting/songs-to-split
STEM_OUT := $(MUSIC_ROOT)/Stem Splitting/stem-output
PN_ROOT := $(MUSIC_ROOT)/Platnium Notes

.DEFAULT_GOAL := help

help:
	@echo "HuntingSzn Music Scripts"
	@echo ""
	@echo "  make sync              Install workspace (uv sync --all-packages)"
	@echo "  make stem-split        Process songs-to-split -> stem-output"
	@echo "  make stem-verify       Verify latest stem folder"
	@echo "  make pn-cleanup        Strip _pn from Platinum Notes filenames"
	@echo "  make platinum-metadata Write ID3 tags from filenames"
	@echo "  make library-dedupe    Remove duplicate artist files in DJ Spotify"
	@echo "  make key-correct-catalog  Step 1: catalog current key tags"
	@echo "  make music-recon       music-script recon (TITLE=... ARTIST=...)"
	@echo "  make music-match       music-script match (TITLE=... ARTIST=...)"
	@echo "  make sc-dl URL=...     Download SoundCloud track"
	@echo "  make yt-dl URL=...     Download YouTube audio"
	@echo "  make sample-inventory  Scan sample/project roots -> CSV"
	@echo "  make test              Run music-script tests"

sync:
	uv sync --all-packages

stem-split:
	uv run --package stem-split stem-split --input "$(STEM_IN)" --output "$(STEM_OUT)"

stem-verify:
	uv run --package stem-split stem-verify

pn-cleanup:
	uv run --package library-tools pn-rename --root "$(PN_ROOT)" $(ARGS)

platinum-metadata:
	uv run --package library-tools library-metadata --root "$(PN_ROOT)" $(ARGS)

library-dedupe:
	uv run --package library-tools library-dedupe $(ARGS)

key-correct-catalog:
	uv run --package library-tools key-correct-catalog $(ARGS)

music-recon:
	uv run --package music-script python -m music_script recon search --title "$(TITLE)" --artist "$(ARTIST)"

music-match:
	uv run --package music-script python -m music_script match --title "$(TITLE)" --artist "$(ARTIST)"

sc-dl:
	uv run --package music-downloads sc-dl "$(URL)"

yt-dl:
	uv run --package music-downloads yt-dl $(ARGS) "$(URL)"

sample-inventory:
	uv run --package music-catalogs sample-inventory $(ARGS)

test:
	uv run --package music-script pytest

lint:
	uv run ruff check packages config
	uv run python -m compileall -q config packages
