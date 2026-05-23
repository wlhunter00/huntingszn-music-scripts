# PRD: GPT trainer (transcript pipeline)

**Status:** Lost — recreate last (largest surface area).

## Purpose

Ingest video/social content → transcripts → enhanced/categorized markdown for OpenAI GPT Builder / custom GPT training.

## Scripts (from inventory)

| Script | Role |
|--------|------|
| `youtube_transcriber.py` | YouTube captions or Whisper fallback |
| `patreon_transcriber.py` | Patreon video ingest |
| `analyze_videos.py` | Analyze transcript content |
| `add_new_creators.py` | Creator registry |
| `enhance_transcripts.py` | LLM/enrichment pass |
| `finalize_transcript.py` | Final formatting |
| `categorize.py` | Bucket transcripts |
| `reorganize_transcripts.py` | Folder restructuring |
| `transcribe_with_speaker_labels.py` | Speaker diarization variant |
| `twitter_scraper.py` / `twitter_batch_scraper.py` / `twitter_example.py` | Twitter ingest |

## Documented workflow order (README)

1. patreon_transcriber (or youtube)
2. analyze_videos
3. add_new_creators
4. enhance_transcripts
5. finalize_transcript
6. categorize

## Dependencies (`requirements.txt`)

```
youtube-transcript-api>=0.6.1
yt-dlp>=2023.12.30
openai-whisper>=20231117
ffmpeg-python>=0.2.0
scikit-learn>=1.0.2
numpy>=1.21.0
tiktoken>=0.3.0
requests>=2.31.0
tweepy>=4.14.0
```

## Data dirs (never commit)

- `transcripts/`, `master_transcripts/`, `old_transcripts/`, `final_folder/`
- `cookies.txt`, `patreon_urls.txt`, `youtube_urls.txt`
- `creator_weights.json`, `repeated_content_flags.json`, `reports/`

## Recreation notes

- Recover data dirs from backup if possible — code without transcripts is useless.
- Split into package with `cli` subcommands per stage.
- OpenAI API keys via `.env` if enhance step uses API.
