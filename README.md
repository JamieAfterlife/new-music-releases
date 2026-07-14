# New Album Releases

A free, automation-first tracker for music released by artists you care about. It uses MusicBrainz rather than Spotify authentication, writes a permanent RSS feed and web page, and runs with only Python 3.11 or newer.

## What it does

- Checks a MusicBrainz artist watchlist for recent releases.
- Preserves release history and never notifies twice for the same release group.
- Uses MusicBrainz's native Album, Single, EP, and Live classifications.
- Includes credited appearances, while excluding releases credited to Various Artists by default.
- Links to exact Spotify, YouTube, or YouTube Music pages when MusicBrainz contains those relationships.
- Falls back to a service-specific search link when an exact relationship is unavailable.
- Generates a release-by-release RSS feed, a grouped 6am daily digest feed, the webpage, and an artist-management page.
- Includes album artwork and tracklists (with available durations) in RSS.
- Prefers the most complete official digital edition on the original release date, so a same-day deluxe or expanded edition wins when it really contains extra tracks.
- Has no Python package dependencies and no API keys.

MusicBrainz data is community maintained, so a release can appear later than it does on streaming services. The tracker checks the previous 45 days each time to catch late additions.

The daily digest is published during the listener's local 6am hour. It lists releases expected that day first, followed by releases made available the previous day, grouped as albums, EPs, singles, features, and other releases. Changing the timezone on the management page automatically changes which hourly workflow run publishes the digest.

## Setup

1. Install Python 3.11 or newer.
2. Copy `config.example.toml` to `config.toml`.
3. Put your email address or website in `musicbrainz.contact`. MusicBrainz requires a meaningful client identity.
4. Add artists:

```powershell
python music_release_tracker.py add "Massive Attack"
python music_release_tracker.py search-artist "Low"
python music_release_tracker.py add "Low" --mbid <the-correct-id>
```

For ambiguous names, use `search-artist`, inspect the country/disambiguation, and add the correct MusicBrainz ID explicitly.

Run a check:

```powershell
python music_release_tracker.py check
```

Open `public/index.html` locally or subscribe to `public/feed.xml` in a feed reader.

The public site title and timezone live in `site.json`. Use an [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), such as `Pacific/Auckland`, so scheduled GitHub builds display the same local time as your computer.

## Using Spotify Release List to bootstrap artists

The hosted Spotify Release List app is useful even though it cannot be our scheduled backend:

1. Sign in at <https://spotifyreleaselist.netlify.app>.
2. Export the available one-month period, include the release categories you want, and keep **Exclude Various Artists** enabled.
3. Export its results as CSV.
4. Import the CSV:

```powershell
python music_release_tracker.py import-csv "C:\path\to\spotify-releases.csv"
```

The importer uses the `Artists`, `Artist IDs`, and related columns to distinguish collaborations from artist names that contain commas. It resolves names to MusicBrainz IDs and reports unresolved names. Review `artists.json` afterward: two musicians can share a name, and the one-month export only includes followed artists who had a release that month. Add dormant artists manually.

Do not copy the Spotify Release List site's client ID or tokens. Those belong to the hosted application and are not a reusable authorization mechanism.

### Export every followed artist

The normal release CSV is limited to one month, so it cannot include dormant artists. While Spotify Release List is signed in, its page can make the same read-only followed-artist request it already uses during refresh.

1. Open <https://spotifyreleaselist.netlify.app>, sign in, and refresh its releases.
2. Open the browser developer console (`F12`, then **Console**).
3. Open `spotify_followed_export.js` from this project, copy its complete contents, paste them into the console, and press Enter. Some browsers ask you to type `allow pasting` before they permit console pasting.
4. The browser downloads `spotify-followed-artists.csv`. It contains only names and Spotify artist IDs—no token.
5. Import it:

```powershell
python music_release_tracker.py import-csv "C:\path\to\spotify-followed-artists.csv"
```

The import is additive and deduplicated by MusicBrainz ID, so it is safe to run after importing the one-month release CSV. The exporter deliberately uses the existing signed-in page rather than copying its token into this project.

### Add artists from a Last.fm library

Last.fm is useful when scrobbles include YouTube or other non-Spotify listening. Its library includes play counts, which lets the importer exclude one-off listens.

With a Last.fm API key, prefer the official importer. The shared secret is not needed:

```powershell
$env:LASTFM_API_KEY = "your-api-key"
python music_release_tracker.py import-lastfm your-username --dry-run
python music_release_tracker.py import-lastfm your-username --min-plays 20
Remove-Item Env:LASTFM_API_KEY
```

The dry run reports how many artists qualify at thresholds from 1 to 100 without changing the watchlist. The importer retains scrobble counts and uses Last.fm-provided MusicBrainz IDs when available.

If you do not want to use an API key, use the browser exporter instead:

1. Open your Last.fm **Library → Artists** page.
2. Open the browser developer console (`F12`, then **Console**).
3. Copy and run the complete contents of `lastfm_library_export.js`.
4. Import the downloaded CSV with a threshold. Twenty scrobbles is a sensible starting point:

```powershell
python music_release_tracker.py import-csv "C:\path\to\lastfm-USER-artists.csv" --min-plays 20
```

The import remains additive and MusicBrainz-ID deduplicated. Lower the threshold later if important artists are missing; rerunning the import will not duplicate existing entries.

The active Last.fm threshold is `tracker.min_lastfm_scrobbles` in `config.toml`. Raising it deactivates Last.fm-only artists below the new value without deleting them; Spotify-derived artists remain active. To lower it, change the setting and rerun `import-lastfm` with the lower `--min-plays` value so the additional artists are added.

`tracker.future_days` controls how far ahead MusicBrainz is searched. It defaults to 90 days. Announced future releases appear with an **Upcoming** label and filter, but Hermes waits until the release date before sending the new-release notification. MusicBrainz can only return future releases that have already been announced and added to its database.

## Blacklist

Edit `blacklist.json` to hide unwanted results from both the RSS feed and the webpage. The saved release history is retained, so removing a blacklist entry restores it without causing a false new-release notification.

- `artists`: exact artist names, including a watched artist responsible for a feature.
- `artist_mbids`: MusicBrainz artist IDs; useful when names can change.
- `release_ids`: individual MusicBrainz release-group IDs.
- `title_contains`: case-insensitive title fragments such as `instrumental` or `remastered`.

After editing the blacklist, rebuild instantly without another API scan:

```powershell
python music_release_tracker.py rebuild
```

Known Last.fm aliases and non-artist entries are handled explicitly in the tracker. This includes renamed bands such as Eskimo Callboy/ Electric Callboy and catalogue artifacts such as compilation titles.

### Manage tracked artists from the website

Open **Manage tracked artists** from the release page. Checked artists are tracked; deselecting an artist moves them to the blacklist, hides their releases, and prevents a later CSV or Last.fm import from re-adding them. The same page can search MusicBrainz and add artists, so Last.fm is optional.

On the first Last.fm-powered build, the management page offers a recent-favourites review. It uses Last.fm's 12-month top-artist chart to show everyone with at least five scrobbles. The listener can select or grey out artists before saving, or keep the simpler default of 50 lifetime scrobbles. Artists explicitly selected during this review stay active even when their lifetime total is below the normal threshold.

Saving requires a fine-grained GitHub token limited to the tracker repository with **Contents: Read and write** permission. To remember it, enter a local unlock password of at least eight characters during the first connection. The token is encrypted in the browser with AES-GCM using a password-derived key and stored under that tracker's URL-specific browser key; the password is never stored. On later visits, enter only the unlock password. The encrypted token can be removed with **Forget saved token**, and neither the token nor password is published with the site. Leaving the unlock password blank keeps the token only in the current tab.

The management page saves the artist list, blacklist, and site settings together in one GitHub update. Removing artists or changing display settings performs a quick rebuild from saved release data. Newly added or re-enabled artists are scanned on their own; the full watchlist scan is reserved for the scheduled 12-hour check or a manual workflow run.

The management page also edits the site title and timezone. **Start fresh** clears both the inherited watchlist and artist blacklist, which makes a fork ready for a different listener without requiring Last.fm.

It can also enable GitHub Issue notifications. When a scheduled check finds released music, the workflow creates one issue containing the release types and Spotify, YouTube Music, and YouTube links. To receive these through email or GitHub Mobile, watch the repository and select **Custom → Issues**. RSS remains available independently.

## Sharing or making a personal copy

The application code does not depend on Jamie's Last.fm account. Someone making their own copy can:

1. Fork or copy the repository and enable its GitHub Pages workflow.
2. Open **Manage tracked artists**, choose **Start fresh**, and set their own title and timezone.
3. Add artists through the built-in MusicBrainz search and save.
4. Optionally import Spotify, Last.fm, or CSV data later.

`data/`, generated pages, local `config.toml`, API keys, and GitHub tokens are not part of the shared repository. The tracked `site.json`, `artists.json`, and `blacklist.json` files are intentionally editable configuration.

## Run every 12 hours with Hermes

Hermes' no-agent cron mode runs a Python script without any model call. It also suppresses delivery when the script prints nothing.

1. Copy `hermes_job.py` to `~/.hermes/scripts/new-music.py` (on native Windows, use the equivalent `.hermes\\scripts` directory).
2. Set `NEW_MUSIC_PROJECT_DIR` for the job to the project directory. Set `NEW_MUSIC_PYTHON` only when Hermes should use a specific Python installation.
3. Ask Hermes to create a no-agent job every 12 hours using `new-music.py`, delivering to your preferred platform.

Equivalent CLI shape:

```text
hermes cron create "every 12h" --no-agent --script new-music.py --deliver telegram --name "new-music"
```

The wrapper uses `--quiet-if-none`, so routine checks generate no message. Failures and newly detected releases produce output.

## Public RSS with GitHub Pages

The included GitHub Actions workflow checks every 12 hours and publishes `public/` to GitHub Pages.

1. Create a public GitHub repository and push this project.
2. In repository **Settings → Pages**, select **GitHub Actions** as the source.
3. Run **Check new music** once from the Actions tab. The workflow identifies itself to MusicBrainz using your public repository URL.

Your page and RSS feed will then be available at the Pages URL. The workflow caches history between runs; RSS readers still deduplicate by the stable MusicBrainz release-group ID if the cache is ever lost.

## Important behavior

- **Appearances:** The tracker searches recording artist credits as well as primary release-group credits and labels each match with the tracked artist responsible. A guest appearance on one track is presented as **Single · Feature**, even when that track belongs to an album; multi-track collaborations keep the container's Album or EP type. Compilations credited to Various Artists remain excluded, as do low-signal releases classified as both a compilation and a demo when the tracked artist only appears on them.
- **Future dates:** Releases dated up to 90 days ahead can appear if MusicBrainz already lists them. They stay out of the default page, RSS, and Hermes notifications until release day.
- **Editions:** Same-day official digital editions are compared by track count. A later deluxe edition remains a later release rather than replacing the original retrospectively.
- **Exact links:** Exact streaming links depend on MusicBrainz relationships. Search links are always included as fallbacks.
- **Public data:** `artists.json`, the generated page, and RSS disclose the artists being tracked if published.
- **State:** `data/state.json` records stable IDs, first-seen times, and discovered exact links. Back it up if running locally.

## Commands

```text
python music_release_tracker.py search-artist "Artist"
python music_release_tracker.py add "Artist"
python music_release_tracker.py add "Artist" --mbid MUSICBRAINZ-ID
python music_release_tracker.py add "Artist" --mbid MUSICBRAINZ-ID --spotify-id SPOTIFY-ID
python music_release_tracker.py import-csv export.csv
python music_release_tracker.py import-csv lastfm-artists.csv --min-plays 20
python music_release_tracker.py import-lastfm USER --dry-run
python music_release_tracker.py import-lastfm USER --min-plays 20
python music_release_tracker.py check
python music_release_tracker.py check --quiet-if-none
python music_release_tracker.py rebuild
python music_release_tracker.py enrich
python music_release_tracker.py enrich --refresh
```
