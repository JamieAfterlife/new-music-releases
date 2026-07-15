# DropSignal technical handover

Last updated: 15 July 2026

Repository: `JamieAfterlife/new-music-releases`

Live site: <https://jamieafterlife.github.io/new-music-releases/>

Stable release: `v2.0.1`

## Handover state

DropSignal 2.0 is live, tested, and considered stable. The repository is a personal deployment, not a multi-user service. It also contains a local gitignored `shareable-template/` directory holding a blank copy for future distribution. The next planned feature line is 2.1 (concerts); no 2.1 implementation has started.

OpenCode supports repository-level `AGENTS.md` rules and project instruction files. This repository includes both `AGENTS.md` and `opencode.json`, so start OpenCode in the repository root and work normally; do not run `/init` unless intentionally replacing the curated instructions.

## Product surfaces

Generated under `public/`:

| Surface | Purpose |
| --- | --- |
| `index.html` | Main release and music-video feed, search, multi-category filters, sorting, upcoming view, ratings, and hide controls. |
| `manage.html` | Tracked artists, recent Last.fm favourites, artist-name fixes, hidden items, video sources/review queues, site settings, themes, and backup import/export. |
| `history.html` | Full-catalogue listening history, 1-5 star ratings, likes/dislikes, filtering, and older MusicBrainz lookup. |
| `videos.html` | Dedicated official-music-video view. |
| `feed.xml` | Item-by-item released-music/video RSS feed. |
| `daily.xml` | Timezone-aware 6am digest: expected today first, then items released yesterday, grouped by type. |
| `manifest.webmanifest` and PWA assets | Installable DropSignal app and offline shell. |

## Architecture and data flow

```text
artists.json + aliases.json + blacklist.json + site.json
                         |
                         v
MusicBrainz / optional Last.fm ----> music_release_tracker.py
                         |                 |
                         |                 +--> data/state.json (runtime cache/history)
                         |                 +--> RSS + HTML + PWA in public/
                         |
optional YouTube API ----> youtube_video_tracker.py
                                           |
video_sources.json + video_decisions.json --+--> data/videos*.json --> main feed/videos/review UI

Browser management/history UI --GitHub Contents API--> tracked JSON files
                                                     |
                                                     v
                                      push workflow rebuilds and deploys Pages
```

The tracker is intentionally dependency-free and uses the Python standard library. MusicBrainz is the canonical release catalogue. Spotify, YouTube Music, and YouTube relationships are used when MusicBrainz supplies exact URLs; otherwise the UI builds service-specific search links.

## Important files

| File | Role and cautions |
| --- | --- |
| `music_release_tracker.py` | Main application. `Settings.load()` merges ignored `config.toml`, tracked `site.json`, and environment overrides. Also renders every page except the dedicated video page. |
| `youtube_video_tracker.py` | Optional YouTube integration. Known channel scans should continue even when discovery quota is exhausted. |
| `*_template.html` | Source UI. They contain inline JavaScript and placeholder tokens replaced during rebuild. |
| `device_auth.js` | Stores a repository-scoped GitHub token in trusted browser storage; keep it out of generated inline duplication except through the existing build path. |
| `artists.json` | Watched MusicBrainz artists and import provenance/scrobble metadata. Personal and public in this repository. |
| `blacklist.json` | Hidden artists, artist MBIDs, release groups, and title fragments. |
| `aliases.json` | Last.fm/credit corrections and ignored non-artist source strings. |
| `ratings.json` | Cross-device rating records and snapshots for older manually added releases. |
| `site.json` | App name, page title, timezone, optional Last.fm username/threshold, notification setting, and onboarding state. |
| `video_sources.json` | Confirmed artist/personal/label YouTube channels and mapped artist names. |
| `video_decisions.json` | Approved/rejected videos and rejected channel suggestions. |
| `data/` | Ignored workflow cache: releases, videos, recent Last.fm review, unresolved names, and channel discovery state. It may be absent in a fresh clone. |
| `public/` | Ignored generated deployment output. Rebuild it; never hand-edit it. |
| `pwa/` | Checked-in source icons and service worker. |
| `.github/workflows/releases.yml` | Push/scheduled scan, optional Last.fm sync, YouTube scan, incremental/full rebuild selection, GitHub Issue notification, Pages deployment. |
| `.github/workflows/daily-digest.yml` | Hourly timezone check and 6am digest deployment from cached state. |
| `shareable-template/` | Local blank distribution. It is deliberately ignored by the personal repository and must be updated separately when reusable behavior changes. |

## Local development

Requirements: Python 3.11+; Node is optional for checking generated inline JavaScript. There is no `requirements.txt` because there are no third-party Python dependencies.

```text
python -m unittest discover -s tests
python music_release_tracker.py rebuild
python youtube_video_tracker.py render
```

On the current Windows workstation:

```text
C:\Users\Jamie\AppData\Local\Programs\Python\Python314\python.exe
```

Run the same unit suite inside `shareable-template/`. At handover, both suites contain 64 tests and pass. Tests intentionally exercise rendered-string behavior as well as Python classification logic.

Commands that contact external services:

```text
python music_release_tracker.py check
python music_release_tracker.py sync-lastfm
python youtube_video_tracker.py scan
```

Use them only when live data is needed. MusicBrainz requests are rate-limited; YouTube discovery consumes quota. `rebuild` is the normal fast path for UI/configuration changes because it reads saved state without scanning MusicBrainz.

## Configuration and credentials

Core MusicBrainz release tracking needs no API key but must use a meaningful `MUSICBRAINZ_CONTACT`. Optional integrations use:

- `LASTFM_API_KEY`: GitHub Actions secret or local environment variable. The Last.fm shared secret is not required.
- `YOUTUBE_API_KEY`: GitHub Actions secret or local environment variable, restricted to YouTube Data API v3.
- `SITE_URL`, `FEED_TITLE`, `TRACKER_TIMEZONE`, `MUSICBRAINZ_CONTACT`: optional build overrides.
- `NEW_MUSIC_PROJECT_DIR`, `NEW_MUSIC_PYTHON`: optional Hermes wrapper settings.

Never place credential values in documentation, configuration committed to Git, logs, test fixtures, or the blank template. The web UI's GitHub token is a fine-grained token limited to this repository with Contents read/write permission. It is stored only in that device's browser storage.

## Deployment behavior and races

Every push to `main` starts **Check new music**. A code/template change normally requests a full scan, while a `[quick rebuild]` commit uses cached state. Scheduled runs scan the full watchlist every 12 hours. The action can commit Last.fm artist imports or discovered YouTube channels back to `main`, and website settings/rating saves also commit directly through GitHub's Contents API.

Therefore:

1. Fetch before editing and again before committing if a workflow or website save ran.
2. Rebase/merge the remote tip; do not discard automated or browser-created JSON changes.
3. Preserve user JSON semantically if resolving conflicts.
4. Expect a pushed workflow to cancel an older Pages run because the Pages concurrency group uses `cancel-in-progress`.
5. Verify the newest run, not a superseded cancelled run.

Ratings specifically use a fresh, no-cache `ratings.json` GET and up to three read/merge/write retries. Do not simplify this back to a single SHA-based PUT; consecutive saves can otherwise reuse a stale browser response.

## Known constraints

- MusicBrainz is community-maintained. New releases can arrive late or have incomplete relationships, tracklists, artwork, or future dates.
- The workflow cache, not Git, holds historical release/video state. A lost cache causes recovery scans; stable release-group IDs prevent duplicate RSS identity, but first-seen timing can change.
- YouTube search/channel discovery is quota-sensitive. Known channel feeds and rendering must remain useful if discovery pauses.
- Exact streaming URLs are best effort. Search URLs are the required fallback.
- Static GitHub Pages means no central user account, private database, server-side session, or instant cross-device write without GitHub commits.
- Keep the personal repository public while it uses GitHub Pages on GitHub Free. Making it private would unpublish Pages; GitHub Pro supports Pages from a private repository, but the published site itself would still be public. A truly private source/data setup would need a separate sanitized public deployment repository and redesigned browser-save workflow.
- Service-worker updates may require closing/reopening or refreshing the installed PWA once.
- The personal tracked artist list, ratings, aliases, and video decisions are intentionally public in this repository.

## Product rules that are easy to regress

- Various Artists is excluded by default.
- Feature matching must identify the tracked artist responsible and reject loose text-only false positives.
- A tracked artist featured on one song from someone else's album is shown as `Single + Feature`.
- Upcoming content is opt-in and closest-first; users should not see unavailable releases by default.
- The user can select multiple release categories simultaneously.
- Same-day deluxe/expanded digital editions win when they contain genuinely additional tracks.
- Label channels are not carte blanche: the mapped tracked artist name must be present in the title.
- Static audio, visualizers, lyric videos, short/vertical content, promos, and backstage material are never music videos, even if previously approved.
- UI language says **Hide**, not **Mute**.
- Management sections default collapsed on mobile.
- Rating stars fill cumulatively from one through the selected number.
- Filters survive navigating to history and back.

## Release status and next work

- `v1.0.0`: preserved original release tracker.
- `v2.0.0`: PWA/DropSignal milestone.
- `v2.0.1`: current stable 2.0, including reliable consecutive rating saves.

Version 2.1 is reserved for concerts. The intended first experiment is Auckland/North Island coverage, including support slots, with Under The Radar for smaller events and Ticketmaster/Live Nation where available. See `V2_ROADMAP.md` and `PROJECT_HISTORY.md` before designing it.

## Definition of done for future changes

1. Preserve the product rules above and the user's live JSON changes.
2. Update both the personal source and the blank `shareable-template/` where the change is reusable.
3. Add or update regression tests.
4. Run both 64-test suites (or their future totals) and rebuild generated output successfully.
5. Use a quick rebuild only when cached metadata is sufficient.
6. Rebase the latest `origin/main`, commit, push, watch the newest Pages workflow, and verify the live file when deployment matters.
7. Update `HANDOVER.md`, `PROJECT_HISTORY.md`, or `V2_ROADMAP.md` when a decision changes.
