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
	@echo "  make pn-pipeline       pn-rename -> pn-filename -> library-metadata (FLIP_STYLE=1 optional)"
	@echo "  make pn-cleanup        Strip _pn from Platinum Notes filenames"
	@echo "  make platinum-metadata Write ID3 tags from filenames"
	@echo "  make library-dedupe    Remove duplicate files in DJ Spotify (filename/extension)"
	@echo "  make serato-clear-cues Remove Serato hot cues from folder (ROOT=..., DRY_RUN=1)"
	@echo "  make wav2mp3 INPUT=... Convert .wav to .mp3 (optional OUTPUT=..., BITRATE=320k)"
	@echo "  make pn-filename ROOT=... Normalize flip filenames for Platinum Notes"
	@echo "  make key-correct-catalog  Step 1: catalog current key tags"
	@echo "  make mashup-recon      mashup-pop-finder recon (TITLE=... ARTIST=...)"
	@echo "  make mashup-match      mashup-pop-finder match (TITLE=... ARTIST=...)"
	@echo "  make sc-dl URL=...     Download SoundCloud track"
	@echo "  make yt-dl URL=...     Download YouTube audio"
	@echo "  make sample-inventory  Scan sample/project roots -> CSV"
	@echo "  make vst-index         Scan VST plugins -> CSV"
	@echo "  make minimal-catalog   Scan Minimal plugin XML -> CSV"
	@echo "  make rift-catalog      Scan Rift presets -> CSV"
	@echo "  make test              Run mashup-pop-finder tests"
	@echo "  make test-library      Run library_tools metadata tests"
	@echo "  make test-cover        Run huntingszn-cover tests"

sync:
	uv sync --all-packages

stem-split:
	uv run --package stem-split stem-split --input "$(STEM_IN)" --output "$(STEM_OUT)"

stem-verify:
	uv run --package stem-split stem-verify

pn-pipeline:
	uv run --package library-tools pn-pipeline --root "$(PN_ROOT)" $(if $(FLIP_STYLE),--flip-style,) $(if $(FORCE),--force,) $(if $(DRY_RUN),--dry-run,) $(ARGS)

pn-cleanup:
	uv run --package library-tools pn-rename --root "$(PN_ROOT)" $(ARGS)

platinum-metadata:
	uv run --package library-tools library-metadata --root "$(PN_ROOT)" $(ARGS)

library-dedupe:
	uv run --package library-tools library-dedupe $(ARGS)

serato-clear-cues:
	uv run --package library-tools serato-clear-cues $(if $(ROOT),--root "$(ROOT)",) $(if $(DRY_RUN),--dry-run,) $(ARGS)

wav2mp3:
	uv run --package library-tools wav2mp3 $(if $(OUTPUT),-o "$(OUTPUT)",) $(if $(BITRATE),-b "$(BITRATE)",) $(if $(OVERWRITE),--overwrite,) "$(INPUT)"

pn-filename:
	uv run --package library-tools pn-filename $(if $(DRY_RUN),--dry-run,) "$(ROOT)"

key-correct-catalog:
	uv run --package library-tools key-correct-catalog $(ARGS)

mashup-recon:
	uv run --package mashup-pop-finder python -m mashup_pop_finder recon search --title "$(TITLE)" --artist "$(ARTIST)"

mashup-match:
	uv run --package mashup-pop-finder python -m mashup_pop_finder match --title "$(TITLE)" --artist "$(ARTIST)" $(if $(KEY),--base-key "$(KEY)",) $(if $(BPM),--base-bpm $(BPM),) $(if $(PAGES),--pages $(PAGES),) $(ARGS)

sc-dl:
	uv run --package music-downloads sc-dl "$(URL)"

yt-dl:
	uv run --package music-downloads yt-dl $(ARGS) "$(URL)"

sample-inventory:
	uv run --package music-catalogs sample-inventory $(ARGS)

vst-index:
	uv run --package music-catalogs vst-index $(ARGS)

minimal-catalog:
	uv run --package music-catalogs minimal-catalog $(ARGS)

rift-catalog:
	uv run --package music-catalogs rift-catalog $(ARGS)

test:
	uv sync --package mashup-pop-finder --extra dev
	uv run --package mashup-pop-finder pytest packages/mashup_pop_finder/tests

test-library:
	uv sync --package library-tools --extra dev
	uv run --package library-tools pytest packages/library_tools/tests

test-cover:
	uv sync --package huntingszn-cover --extra dev
	uv run --package huntingszn-cover pytest packages/huntingszn_cover/tests

lint:
	uv run ruff check packages config
	uv run python -m compileall -q config packages
