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
- B2: bind `RCLONE_CONFIG_B2_TYPE=b2`, `RCLONE_CONFIG_B2_ACCOUNT=secret:personal:RCLONE_CONFIG_B2_ACCOUNT`, `RCLONE_CONFIG_B2_KEY=secret:personal:RCLONE_CONFIG_B2_KEY` in exec `env`. Only `rclone copy`, `copyto`, and `lsf`. Never `sync`, `delete`, `move`, or `purge`.
- Browser split: SoundCloud's DataDome blocks sign-in in Chrome on Linux Devin VMs (140.232.64.x IPs), even on fresh machines and with Will driving by hand. Gates needing SoundCloud login or Spotify connect run in Aside (https://aside.com) on a Windows Devin child (`platform: "windows"`); Aside was not blocked from the same IP range. Email-only gates and direct links can stay in the Linux parent's Chrome.
- Aside setup (once per Windows machine): child installs Aside for Windows x64 and launches it. Ask Will to sign into Aside (email code to his Aside account; he gives the code), then SoundCloud and Spotify in Aside himself. Devin typing Spotify credentials hit reCAPTCHA; Will signing in by hand once fixed it. Logins exist only on that machine: reuse the same Windows session across passes; ask Will to sign in again on a new machine.
- Child drives Aside with computer use, following all gate rules below (OAuth approved/denied apps, comment `fire`, captcha means script fallback). Gate email: secret `GATE_EMAIL` (type `${secret:...}` references, never the value). Parent fetches emailed download links from Gmail through MCP and passes them to the child.
- Repo: `~/repos/huntingszn-music-scripts`, run `uv sync` once if needed.

## Rules
- Gate UI first (WAV/original quality). Use the script only for Laylo, Droploud, no gate, or a gate that failed.
- Share as little as possible. Skip every optional step. Never enter Will's real email, name, or personal info. If a gate asks for name and email, use First name `HuntingSzn` and the `GATE_EMAIL` inbox, untick the marketing boxes, and keep going.
- Hypeddit, ToneDen, and similar gates can't enforce SoundCloud steps (follow/like/comment/repost icons) or Instagram steps: click each button, close the popup or tab right away without doing anything, and continue. Hypeddit buttons (Share email, icons, Next, Download) can be covered by an overlay; if a click doesn't take, scroll it into view (parent's Chrome can also use the browser console / CDP). Downloads can take about a minute to start.
- Spotify connect is enforced. In the child's Aside, click the gate's opt-out for saving future songs before connecting with Will's existing Spotify login.
- pl8list: its own login page shows a Cloudflare check, but the track page's download button works. Use the track-page flow.
- Droploud really needs a repost, and SoundCloud may block reposts from this VM's IP; if it does, use the script (or ask Will to repost if he wants the original).
- ipln.io (InfluencePlanner) gates can repost on HuntingSzn by themselves, so the repost cleanup step is mandatory.
- Do NOT run the repo's `sc-unrepost` (`packages/soundcloud_repost`): it deletes ALL reposts, not just today's.

## SoundCloud OAuth ("act on your behalf") apps
- Approved: stillhype.io, droploud.com, pl8list.com (allow, then repost cleanup).
- Denied: ipln.io / InfluencePlanner (use the script).
- New platform asks for access: cancel, finish the rest of the batch, then ask Will one `user_question` per platform: "<platform> wants to connect to your SoundCloud for <track>. Approve and add it?" (Yes / No). Yes: rerun that gate and open a PR adding it to Approved here. No: use the script, log the reason, and add it to Denied.
- Captcha (reCAPTCHA, hCaptcha, Spotify/SoundCloud "prove you're human"): don't solve it or ask Will to; close it and use the script for that track.
- Default comment: when an approved gate requires a SoundCloud comment, post exactly `fire`. Never use the gate's suggested text.

## Steps
1. **Find the last pass.** `rclone lsf --dirs-only b2:huntingszn-music/Downloads/ | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}/$' | sort | tail -1` is the last pass date; read its `REPORT.md` if it has one for the tracks it covered.
2. **Read the likes** on https://soundcloud.com/huntingszn/likes (newest first; scroll) back to the tracks covered in the last pass. If you're unsure where the last pass stopped, overlap a bit; the dedupe step drops repeats. A quick list of URLs: `uv run --package music-downloads yt-dlp --flat-playlist --print url https://soundcloud.com/huntingszn/likes` (the likes are public).
3. **Gate link per track.** On each track page, take the "Buy This Track" link. It's a `gate.sc?url=` redirect: decode the target URL and drop the token. If there's no Buy button, check the description for a gate link (e.g. ToneDen, Hypeddit). Pages load slowly; wait for the track header.
4. **Dedupe** against `rclone lsf -R --files-only b2:huntingszn-music` (save it to a file once and grep it). Match title AND artist/remixer: the same title by a different artist is not a dupe (e.g. Conrad's "car crash" remix of the jigitz song vs the original `car crash.mp3`). Confirm the artist from SoundCloud/Spotify metadata before skipping; only skip true matches of the same version.
5. **Sort by gate type:** Hypeddit / ToneDen / stillhype / other browser gates go to the browser; Laylo, Droploud (if the repost is blocked), denied platforms, and no-gate tracks go to the script.
6. **Browser gates**, a few tracks at a time, split between parent's Chrome and child's Aside as above. Child attaches each downloaded file to its session; parent pulls them with `download_attachment`. Parent's Chrome downloads land in `~/Downloads`. On the Linux parent, unzip any zip and skip `__MACOSX`; rename files `Artist - Title (Remix).ext`. If a pack has several versions (original, extended, instrumental), upload only the Extended one ("Ext Intro" / "Extended Mix"); if there's no extended version, upload the main mix only.
7. **Script fallback:** `cd ~/repos/huntingszn-music-scripts && uv run --package music-downloads sc-dl --output-dir <dir> <urls>`. Files are named by SoundCloud title only, so if two tracks share a title, run them with separate `--output-dir`s and rename to `Artist - Title` before uploading. These are lower quality (SoundCloud stream, often 128–160k); flag them. Log the reason for each one (Laylo, Droploud, no gate, denied platform, or failed gate + what failed).
8. **Upload (Linux parent only):** `rclone copy <file-or-dir> b2:huntingszn-music/Downloads/<YYYY-MM-DD>/`, then check with `rclone lsf`.
9. **Repost cleanup (always):** child opens https://soundcloud.com/huntingszn/reposts in Aside (reload if it shows offline/empty) and removes any repost a gate added today (Repost button > Delete repost). Don't touch older reposts, likes, follows, or comments. Reload to confirm.
10. **Report:** write `REPORT.md` and upload it with `rclone copyto REPORT.md b2:huntingszn-music/Downloads/<YYYY-MM-DD>/REPORT.md` (not `copy`, which would create `REPORT.md/REPORT.md`) (append a section per batch). For each track list the source (gate type, or script + reason), format/bitrate, and the repost-check result; also list skipped dupes, and any comments, follows, or reposts a gate made and whether they were removed. Send Will a short summary and propose a PR to this skill for any new gate behavior.
