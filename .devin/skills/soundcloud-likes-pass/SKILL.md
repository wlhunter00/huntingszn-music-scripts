---
name: soundcloud-likes-pass
description: >-
  Use when Will wants to pull new SoundCloud likes (tracks not yet on B2) into
  b2:huntingszn-music/Downloads/<YYYY-MM-DD>/ for review, via download-gate UIs
  in the browser first and the sc-dl script as fallback.
---
# SoundCloud likes download pass

Goal: download tracks liked on the HuntingSzn SoundCloud account (https://soundcloud.com/huntingszn/likes) since the last pass that are missing from B2, into `b2:huntingszn-music/Downloads/<YYYY-MM-DD>/` for review (Platinum Notes comes later). B2 is a full mirror of the HuntingSzn drive, so checking B2 is enough.

## Setup
- B2: bind `RCLONE_CONFIG_B2_TYPE=b2`, `RCLONE_CONFIG_B2_ACCOUNT=secret:personal:RCLONE_CONFIG_B2_ACCOUNT`, `RCLONE_CONFIG_B2_KEY=secret:personal:RCLONE_CONFIG_B2_KEY` in exec `env`. Only `rclone copy` / `lsf`. Never `sync`, `delete`, `move`, or `purge`.
- SoundCloud: log in with the Chrome browser using secrets `SOUNDCLOUD_USERNAME` / `SOUNDCLOUD_PASSWORD` (type `${secret:...}` references, never the value). If SoundCloud asks for a captcha you can't solve, or a new-device code, stop and ask Will.
- Spotify (for Spotify-connect gates): secrets `SPOTIFY_USERNAME` / `SPOTIFY_PASSWORD`, filled the same way.
- Gate email: the inbox Will connected through MCP (address in secret `GATE_EMAIL`). Read emailed download links from that inbox with the MCP tools.
- Repo: `~/repos/huntingszn-music-scripts`, run `uv sync` once if needed.

## Rules
- Gate UI first (WAV/original quality). Use the script only for Laylo, Droploud, no gate, or a gate that failed.
- Share as little as possible. Skip every optional step. Never enter Will's real email, name, or personal info. If a gate asks for name and email, use First name `HuntingSzn` and the `GATE_EMAIL` inbox, untick the marketing boxes, and keep going.
- Hypeddit, ToneDen, and similar gates can't enforce SoundCloud steps (follow/like/comment/repost icons) or Instagram steps: click each button, close the popup or tab right away without doing anything, and continue. Hypeddit buttons (Share email, icons, Next, Download) can be covered by an overlay; if a click doesn't take, scroll it into view or click it via the browser console / CDP. Downloads can take about a minute to start.
- Spotify connect is enforced. Before connecting, click the gate's opt-out for saving future songs, then sign in with the Spotify secrets.
- Droploud really needs a repost, and SoundCloud may block reposts from this VM's IP; if it does, use the script (or ask Will to repost if he wants the original).
- ipln.io (InfluencePlanner) gates can repost on HuntingSzn by themselves, so the repost cleanup step is mandatory.
- Do NOT run the repo's `sc-unrepost` (`packages/soundcloud_repost`): it deletes ALL reposts, not just today's.

## SoundCloud OAuth ("act on your behalf") apps
- Approved: stillhype.io, droploud.com (allow, then repost cleanup).
- Denied: ipln.io / InfluencePlanner (use the script).
- New platform asks for access: cancel, finish the rest of the batch, then ask Will one `user_question` per platform: "<platform> wants to connect to your SoundCloud for <track>. Approve and add it?" (Yes / No). Yes: rerun that gate and open a PR adding it to Approved here. No: use the script, log the reason, and add it to Denied.
- Default comment: when an approved gate requires a SoundCloud comment, post exactly `fire`. Never use the gate's suggested text.

## Steps
1. **Find the last pass.** `rclone lsf --dirs-only b2:huntingszn-music/Downloads/ | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}/$' | sort | tail -1` is the last pass date; read its `REPORT.md` if it has one for the tracks it covered.
2. **Read the likes** on https://soundcloud.com/huntingszn/likes (newest first; scroll) back to the tracks covered in the last pass. If you're unsure where the last pass stopped, overlap a bit; the dedupe step drops repeats. A quick list of URLs: `uv run yt-dlp --flat-playlist --print url https://soundcloud.com/huntingszn/likes` (the likes are public).
3. **Gate link per track.** On each track page, take the "Buy This Track" link. It's a `gate.sc?url=` redirect: decode the target URL and drop the token. If there's no Buy button, check the description for a gate link (e.g. ToneDen, Hypeddit). Pages load slowly; wait for the track header.
4. **Dedupe** against `rclone lsf -R --files-only b2:huntingszn-music` (save it to a file once and grep it). Match title AND artist/remixer: the same title by a different artist is not a dupe (e.g. Conrad's "car crash" remix of the jigitz song vs the original `car crash.mp3`). Confirm the artist from SoundCloud/Spotify metadata before skipping; only skip true matches of the same version.
5. **Sort by gate type:** Hypeddit / ToneDen / stillhype / other browser gates go to the browser; Laylo, Droploud (if the repost is blocked), denied platforms, and no-gate tracks go to the script.
6. **Browser gates**, a few tracks at a time, following the rules above. Files land in `~/Downloads`. Unzip any zip and skip `__MACOSX`. If a pack has several versions (original, extended, instrumental), upload only the Extended one ("Ext Intro" / "Extended Mix"); if there's no extended version, upload the main mix only.
7. **Script fallback:** `cd ~/repos/huntingszn-music-scripts && uv run --package music-downloads sc-dl --output-dir <dir> <urls>`. These are lower quality (SoundCloud stream, often 128–160k); flag them. Log the reason for each one (Laylo, Droploud, no gate, denied platform, or failed gate + what failed).
8. **Upload:** `rclone copy <file-or-dir> b2:huntingszn-music/Downloads/<YYYY-MM-DD>/`, then check with `rclone lsf`.
9. **Repost cleanup (always):** open https://soundcloud.com/huntingszn/reposts (reload if it shows offline/empty) and remove any repost a gate added today (Repost button > Delete repost). Don't touch older reposts, likes, follows, or comments. Reload to confirm.
10. **Report:** write `REPORT.md` and `rclone copy` it to `b2:huntingszn-music/Downloads/<YYYY-MM-DD>/REPORT.md` (append a section per batch). For each track list the source (gate type, or script + reason), format/bitrate, and the repost-check result; also list skipped dupes, and any comments, follows, or reposts a gate made and whether they were removed. Send Will a short summary and propose a PR to this skill for any new gate behavior.
