# huntingszn-cover

Album cover art tool for HuntingSzn: fetch album covers via SerpAPI, transform with OpenAI image edit, and create mashup composites.

## Features

- **fetch**: Search for album cover images using SerpAPI Google Images, deduplicate with perceptual hashing (imagehash)
- **transform**: Apply aesthetic transformations using OpenAI's image edit API (gpt-image-1.5)
- **mashup**: Create composite album covers from multiple tracks with automatic transformation

## Installation

```bash
# From workspace root
uv sync

# Or install directly
uv pip install -e packages/huntingszn_cover
```

## Requirements

### API Keys

- `SERPAPI_API_KEY` - Required for image fetching. Get one at https://serpapi.com/
- `OPENAI_API_KEY` - Required for image transformation. Get one at https://platform.openai.com/

Set these as environment variables or in a `.env` file.

## Usage

### Fetch Album Covers

```bash
huntingszn-cover fetch \
    --tracks "Olivia Rodrigo:The Cure" \
    --tracks "Illenium:Pray" \
    --output ./covers \
    --count 5
```

Fetches ~5 unique square album covers per track using SerpAPI Google Images. Images are deduplicated using perceptual hashing.

### Transform Images

```bash
huntingszn-cover transform \
    --image cover.png \
    --prompts clean \
    --prompts crystal \
    --output ./transformed
```

Transforms an image using OpenAI's image edit API with the specified prompt types:
- `clean`: Minimalist, polished aesthetic
- `crystal`: Teal/crystal aesthetic with ethereal effects

**Note**: This uses OpenAI IMAGE EDIT (not text-to-image generation). The source image is always used as input.

### Create Mashup

```bash
huntingszn-cover mashup \
    --mashup "The Cure x Pray" \
    --tracks "Olivia Rodrigo:The Cure" \
    --tracks "Illenium:Pray"
```

**Default behavior** (web fetch is required, not optional):
1. **ALWAYS** fetches fresh album covers via SerpAPI Google Images (~5 per track)
2. Auto-selects the best square cover per track (default, use `--pick` to manually select)
3. Creates a composite via OpenAI multi-image edit (`gpt-image-1.5`, fallback `gpt-image-1`)
4. Transforms composite + each original with clean and crystal prompts
5. Generates `manifest.json` tracking all outputs
6. Copies to `/Volumes/HuntingSzn/Thumbnails/Releases/<Mashup Name>/` if mounted

**Important**: Does NOT read from or overwrite existing Releases folders - those are finished work only. A new run for "The Cure x Pray" will Google those two covers fresh; it will not open or clobber the existing release folder. If the volume destination already exists, the local mashup still succeeds and the copy is skipped.

**If OpenAI image edit fails** (after trying `gpt-image-1.5` then `gpt-image-1`), the command fails clearly. It does not silently replace the mashup with a Pillow 50/50 split.

**If fetch returns unusable results**, the command fails clearly with a list of candidate paths. Use `--image` as a rare override only:

```bash
# Rare override when fetch returns junk
huntingszn-cover mashup \
    --mashup "The Cure x Pray" \
    --tracks "Olivia Rodrigo:The Cure" \
    --tracks "Illenium:Pray" \
    --image /path/to/cure-cover.jpg \
    --image /path/to/pray-cover.jpg
```

## Naming Conventions

### Releases Directory

Default volume path: `/Volumes/HuntingSzn/Thumbnails/Releases/`

Folders are named using the **mashup name** (not a slug), matching how audio releases are organized:
- Audio title: `The Cure x Sad Songs x Pray`
- Folder name: `The Cure x Pray` (often shorter, focusing on key tracks)

When copying to the volume, the `--mashup` name is used directly as the folder name.

### Vendor Originals

You may see existing originals in release folders with these naming patterns:
- SoundCloud: `artworks-…-t500x500.jpg`
- Spotify: `ab67616d0000b273….jpg`
- Generic: `download.jpg`, UUID-based `.png` files

Fetched images are saved under `originals/<track-slug>/` with sequential naming (`cover_00.png`, etc.).

### Our Output Naming

Transformed outputs follow this pattern:
- `<slug>-composite.png` - Raw composite
- `<slug>-composite-clean.png` - Composite with clean prompt
- `<slug>-composite-crystal.png` - Composite with crystal prompt
- `<track-slug>-clean.png` - Individual track, clean
- `<track-slug>-crystal.png` - Individual track, crystal

**Note**: Renaming to `final.png` or similar is a human task - this tool does not auto-rename outputs.

### ChatGPT Outputs (Historical)

Previous ChatGPT image generations used: `ChatGPT Image MMM DD, YYYY, HH_MM_SS AM.png`

Our tool uses the structured naming above instead.

## Prompt Files

Prompts are loaded at runtime from these locations (in order):

1. Environment variables: `HUNTINGSZN_PROMPT_CLEAN`, `HUNTINGSZN_PROMPT_CRYSTAL`
2. Package prompts: `huntingszn_cover/prompts/album-prompt-*.txt`
3. Workspace: `./huntingszn-assets/cover-prompts/album-prompt-*.txt` (relative to cwd)
4. Volume: `/Volumes/HuntingSzn/Thumbnails/Album Prompt - *.txt`

The wordmark in prompt files should be `HUNTINGSZN EDIT` (not FLIP).

**Important**: Prompt files already forbid adding extra logos. Brand assets live at `/Volumes/HuntingSzn/Thumbnails/Logos/` - do not bake additional logos into transforms.

## Output Structure

```
./covers/<slug>/
├── manifest.json
├── <slug>-composite.png
├── <slug>-composite-clean.png
├── <slug>-composite-crystal.png
├── originals/
│   ├── <track1-slug>/
│   │   ├── cover_00.png
│   │   └── cover_01.png
│   └── <track2-slug>/
│       └── ...
└── transformed/
    ├── <track1-slug>/
    │   ├── <track1-slug>-clean.png
    │   └── <track1-slug>-crystal.png
    └── ...
```

When copied to volume:
```
/Volumes/HuntingSzn/Thumbnails/Releases/<Mashup Name>/
└── (same structure as above)
```

## Scope

This package handles **image assets only**:
- Album cover fetching
- Image transformation
- Composite creation

**Not in scope**: videos, audio files (wav/mp3), .env files, databases (sqlite).

## Development

```bash
# Run tests
uv run pytest packages/huntingszn_cover/tests -v

# Run linting
uv run ruff check packages/huntingszn_cover
uv run ruff format --check packages/huntingszn_cover
```

## Technical Notes

- Uses OpenAI `gpt-image-1.5` (falls back to `gpt-image-1`) for image edits
- Image edit API endpoint: `POST /v1/images/edits`
- Output format: 1024x1024 PNG
- `gpt-image-1.5` supports multiple input images for mashup composites
- Perceptual hash threshold: 8 (Hamming distance)
