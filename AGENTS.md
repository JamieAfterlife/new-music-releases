# DropSignal agent instructions

DropSignal is a personal, static new-music tracker. It is built with Python 3.11+ and browser-native HTML/CSS/JavaScript, has no Python package dependencies, and deploys to GitHub Pages through GitHub Actions. The current stable release is `v2.0.1`.

Read `HANDOVER.md` before making architectural or deployment changes. Read `PROJECT_HISTORY.md` when a task affects product behavior, matching rules, naming, or UX. `opencode.json` also loads both files automatically in OpenCode.

## Source of truth

- `music_release_tracker.py`: MusicBrainz/Last.fm logic, release classification, RSS, daily digest, page generation, PWA generation, and CLI.
- `youtube_video_tracker.py`: YouTube channel discovery, video classification, review state, and video-page rendering.
- `web_template.html`, `manage_template.html`, `history_template.html`, and `videos_template.html`: editable page sources.
- `device_auth.js`: trusted-device GitHub-token storage shared by management and history pages.
- `pwa/`: checked-in PWA source assets.
- `tests/`: standard-library `unittest` suites.
- Root JSON files are live user configuration and decisions. Preserve them and merge concurrent changes carefully.
- `public/` and `data/` are generated/runtime directories and are gitignored. Never implement a fix by editing `public/` directly.
- `config.toml` is local and ignored; `config.example.toml` is the public example.
- `shareable-template/` is a local, ignored blank distribution. Mirror reusable code, tests, documentation, workflows, and PWA changes there without copying Jamie's artists, ratings, site identity, blacklists, aliases, or video decisions.

## Verification

Run from the repository root:

```text
python -m unittest discover -s tests
python music_release_tracker.py rebuild
```

Then run the blank-template suite:

```text
cd shareable-template
python -m unittest discover -s tests
```

On Jamie's Windows PC, Python is at `C:\Users\Jamie\AppData\Local\Programs\Python\Python314\python.exe` if `python` is not on `PATH`.

For HTML/JavaScript changes, rebuild first and syntax-check the inline scripts in the generated page with Node when available. Browser QA is useful for interaction or responsive-layout changes but is not required for data-only or documentation changes.

## Required behavior

- Exclude Various Artists by default and include genuine tracked-artist appearances.
- A one-track guest appearance is `Single + Feature`, not the containing album. Multi-track collaborations can retain Album or EP.
- Upcoming releases are hidden by default; their view sorts the closest release first. Released items keep the established date/type/alphabetical ordering and multi-select category filters.
- Prefer complete same-day digital/deluxe editions when they contain additional tracks. Do not replace an earlier release with a deluxe edition released later.
- Label-channel videos must mention a mapped tracked artist in the title. Ignore Topic channels, Shorts, videos under 60 seconds, vertical videos, trailers, promos, recaps, highlights, official audio, visualizers, lyric videos, vlogs, and behind-the-scenes material.
- Ratings are 1-5 stars; 4-5 are likes and 1-3 are dislikes. Consecutive saves must fetch fresh `ratings.json`, merge, and retry GitHub SHA conflicts.
- Use the word **Hide**, not **Mute**, for removing releases or videos from public views.
- Preserve mobile-first management: major sections start collapsed, selected-star highlighting includes every star to the left, and release filter choices persist on the device.
- Keep the themes named Green, Red, Purple, and Grey.

## GitHub and deployment safety

- Pushing `main` starts `.github/workflows/releases.yml`; it scans videos, rebuilds the site, and deploys GitHub Pages.
- The scheduled full release scan runs every 12 hours. The daily-digest workflow checks hourly and publishes during the configured local 6am hour.
- Website saves and the Actions bot can advance `origin/main` while work is in progress. Fetch and rebase before committing, and never overwrite newer `artists.json`, `blacklist.json`, `site.json`, `ratings.json`, `aliases.json`, `video_sources.json`, or `video_decisions.json`.
- Add `[quick rebuild]` to a commit only when saved state can be rebuilt without a full MusicBrainz scan. Do not use it for changes that require refetching release metadata.
- Never force-move release tags. `v1.0.0`, `v2.0.0`, and `v2.0.1` are historical markers.
- Do not commit credentials. GitHub Actions expects optional `LASTFM_API_KEY` and `YOUTUBE_API_KEY` secrets. The Last.fm shared secret is unused. Repository-scoped GitHub tokens belong only in browser trusted-device storage.

## Scope

Version 2.0 is complete. Normal work should be bug fixes and polish. The next planned product feature is concerts in 2.1; see `V2_ROADMAP.md`. Accounts, push notifications, automatic playlists, and a paid/shared backend remain deferred unless Jamie explicitly reopens them.
