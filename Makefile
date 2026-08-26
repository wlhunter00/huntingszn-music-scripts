# HuntingSzn Music Scripts — run from repo root with uv
# Default: parent of this repo (the portable HDD when Scripts lives on it).
# Override: make MUSIC_ROOT="/Volumes/Will Hunter Music" ...
MUSIC_ROOT ?= $(abspath $(CURDIR)/..)
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
	@echo "  make sync-stem-cpu     Sync stem-split with CPU extra (no NVIDIA)"
	@echo "  make sync-stem-gpu     Sync stem-split with GPU extra (NVIDIA CUDA)"
	@echo "  make sync-stem-mac     Sync stem-split with macOS extra (MLX)"
	@echo "  make stem-split        Process songs-to-split -> stem-output"
	@echo "  make stem-verify       Verify latest stem folder"
	@echo "  make pn-pipeline       pn-rename -> pn-filename -> library-metadata (FLIP_STYLE=1 optional)"
	@echo "  make pn-cleanup        Strip _pn from Platinum Notes filenames"
	@echo "  make platinum-metadata Write ID3 tags from filenames"
	@echo "  make library-dedupe    Remove duplicate files in DJ Spotify (filename/extension)"
	@echo "  make serato-clear-cues Remove Serato hot cues from folder (ROOT=..., DRY_RUN=1)"
	@echo "  make mik-clear-cues    Remove Mixed In Key cue points (ROOT=folder required, DRY_RUN=1)"
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
	@echo "  make library-index     Index library to SQLite"
	@echo "  make library-publish   Publish library to B2"
	@echo "  make library-pull      Pull allowlisted B2 prefixes + Ableton remap"
	@echo "  make library-watch     Watch for the music drive (ONCE=1 for one-shot)"
	@echo "  make library-install-watch  Install per-PC login stub (launchd / Task Scheduler)"
	@echo "  make library-query     Query library (CAMELOT=..., BPM=..., Q=...)"
	@echo "  make test              Run mashup-pop-finder tests"
	@echo "  make test-library      Run library_tools metadata tests"
	@echo "  make test-library-sync Run library_sync tests"
	@echo "  make test-cover        Run huntingszn-cover tests"

sync:
	uv sync --all-packages

sync-stem-cpu:
	uv sync --package stem-split --extra cpu

sync-stem-gpu:
	uv sync --package stem-split --extra gpu

sync-stem-mac:
	uv sync --package stem-split --extra mac

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

mik-clear-cues:
	@test -n "$(ROOT)" || (echo 'mik-clear-cues requires ROOT=/path/to/folder'; exit 1)
	uv run --package library-tools mik-clear-cues $(if $(DRY_RUN),--dry-run,) "$(ROOT)" $(ARGS)

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

library-index:
	uv run --package library-sync library-sync index $(if $(DRY_RUN),--dry-run,) $(ARGS)

library-publish:
	uv run --package library-sync library-sync publish $(if $(DRY_RUN),--dry-run,) $(if $(SKIP_INDEX),--skip-index,) $(if $(ALLOW_DELETE),--allow-delete,) $(ARGS)

library-pull:
	uv run --package library-sync library-sync pull $(if $(DRY_RUN),--dry-run,) $(ARGS)

library-watch:
	uv run --package library-sync library-sync watch $(if $(ONCE),--once,) $(if $(DRY_RUN),--dry-run,) $(ARGS)

library-install-watch:
	uv run --package library-sync library-sync install-watch $(if $(DRY_RUN),--dry-run,) $(ARGS)

library-query:
	uv run --package library-sync library-sync query $(if $(CAMELOT),--camelot "$(CAMELOT)",) $(if $(BPM),--bpm $(BPM),) $(if $(Q),--q "$(Q)",) $(if $(ROLE),--role $(ROLE),) $(if $(LIMIT),--limit $(LIMIT),) $(if $(JSON),--json,) $(ARGS)

test-library-sync:
	uv sync --package library-sync --extra dev
	uv run --package library-sync pytest packages/library_sync/tests

test-cover:
	uv sync --package huntingszn-cover --extra dev
	uv run --package huntingszn-cover pytest packages/huntingszn_cover/tests

lint:
	uv run ruff check packages config
	uv run python -m compileall -q config packages
