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
    --tracks "Illenium:Pray" \
    --auto \
    --output /workspace/huntingszn-assets/covers
```

Full pipeline:
1. Fetches album covers for each track
2. Auto-selects the most square covers
3. Creates a composite via OpenAI multi-image edit (falls back to Pillow 50/50 split)
4. Transforms composite + each original with clean and crystal prompts
5. Generates `manifest.json` tracking all outputs
6. Optionally copies to `/Volumes/HuntingSzn/Thumbnails/Releases/` if mounted

## Prompt Files

Prompts are loaded at runtime from these locations (in order):

1. Environment variables: `HUNTINGSZN_PROMPT_CLEAN`, `HUNTINGSZN_PROMPT_CRYSTAL`
2. Package prompts: `huntingszn_cover/prompts/album-prompt-*.txt`
3. Workspace: `/workspace/huntingszn-assets/cover-prompts/album-prompt-*.txt`
4. Volume: `/Volumes/HuntingSzn/Thumbnails/Album Prompt - *.txt`

The wordmark in prompt files should be `HUNTINGSZN EDIT` (not FLIP).

## Output Structure

```
/workspace/huntingszn-assets/covers/<slug>/
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
