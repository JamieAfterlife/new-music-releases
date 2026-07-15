# DropSignal project history and decision log

This is a sanitized reconstruction of the product conversation through 15 July 2026. It records context that is not obvious from code or commit messages. It intentionally excludes API keys, shared secrets, GitHub tokens, passwords, and private browser-storage material.

## Origin

Jamie wanted a free replacement for Music Butler that reports new releases from favourite artists. Listening happens mainly on YouTube Music, but its metadata was considered unreliable; Spotify is available but not Premium. The desired result needed Album/EP/Single/Live/Feature labels, links to Spotify, YouTube Music, and YouTube, Various Artists exclusion, a public page, RSS, and 12-hour automation.

The first reference UI was Spotify Release List. Its clean dark layout, coloured release-type borders/text, type-first grouping, and alphabetical secondary sorting became the visual and interaction baseline. Its one-month export was useful only for bootstrapping.

## Foundational decisions

- MusicBrainz is the canonical release source because it is free, structured, does not require Spotify Premium or authentication, and includes non-Spotify releases.
- Spotify/YouTube links are exact when MusicBrainz provides them and search fallbacks otherwise.
- Last.fm is the preferred artist-library source because Jamie's scrobbles include YouTube listening. The active personal threshold was eventually lowered from 50 to 20 lifetime scrobbles, with a first-run review of artists having at least five scrobbles in the previous 12 months.
- Artist identity uses MusicBrainz IDs, not names alone. The site also supports manual MusicBrainz search, aliases, ignored non-artist credits, checked/greyed watchlist controls, blacklist restoration, and a blank-template start.
- GitHub Pages and GitHub Actions were selected over a separate Vercel deployment because the product is static, already needs GitHub for scheduled automation/stateful configuration, and does not need a backend.
- Keep the current repository public while it relies on GitHub Free Pages. A private repository would unpublish the site on Free, and a Pro-hosted Pages site would still expose the published pages. A future privacy redesign would separate private source/data from a sanitized public deployment repository.
- Hermes became optional. Its job must use no-agent script mode so routine scans consume no model tokens and stay silent when no new music exists.
- Personal deployment is public and intentionally discloses the tracked artists. Credentials must never be published.

## Version 1 evolution

The initial Python tracker imported artists, queried MusicBrainz, stored seen release groups, produced RSS and HTML, and supported a 12-hour scheduled check. It then gained:

- A custom blacklist.
- Spotify-like dark visual styling with colour-coded Albums, EPs, Singles, Live releases, and Features.
- Type ordering followed by alphabetical ordering, plus released-date and upcoming-date behavior.
- Future releases up to 90 days ahead, hidden by default and shown closest-first only in Upcoming.
- A public GitHub Pages deployment and RSS tracklists/artwork.
- Same-day deluxe preference when the deluxe version genuinely has extra tracks.
- Website-based artist management and a blank shareable configuration.
- Last.fm username onboarding and recent-favourites review.
- Incremental rebuilds so toggling an existing artist or setting does not rescan the entire library.
- Cross-device GitHub-backed configuration using a repository-scoped token and trusted-device option.

Version 1 is frozen at `v1.0.0`.

## Matching bugs and the rules they established

Several real results exposed important distinctions:

- An unrelated release group by Lamorn appeared despite Lamorn not being tracked. Matching was tightened to avoid loose relationship/text false positives.
- *Washington State Charm* by Monument of Misanthropy said “Matched via Enterprise Earth.” The relationship itself was acceptable, but a guest on only one song must make the surfaced item `Single + Feature`, not Album + Feature.
- *End of You* by Poppy, Amy Lee, and Courtney LaPlante existed in MusicBrainz but Last.fm supplied a combined credit string. Combined credits can be ignored as pseudo-artists while the three real artists remain tracked.
- Last.fm supplied “The Fever 33,” which needed a manual correction to FEVER 333. Artist-name fixing must allow a different search query and keep the search results visibly within the same expanded section.
- Name-fix, artist-addition, and review sections default collapsed because long mobile pages made controls difficult to reach.
- Exact titles, joins, aliases, and MusicBrainz IDs matter more than fuzzy name similarity when ambiguity can introduce another artist's catalogue.

Do not remove regression tests around these cases without replacing the behavior they protect.

## Version 2 decisions and implementation

### Daily digest RSS

The daily feed publishes in the configured timezone's 6am hour. It begins with releases expected that day, which is normally short, then items made available yesterday. Each section groups Albums, EPs, Singles, Features, then other items. The ordinary item-by-item RSS feed remains available.

### Music videos

MusicBrainz video relationships were too sparse, so official-video tracking uses YouTube Data API v3 and known channel mappings.

Channel and classification lessons:

- Artist channels, personal channels, and record-label channels are supported.
- Alex Terrible is mapped to Slaughter to Prevail because some band videos appear on his personal channel.
- Auto-generated `- Topic` channels are ignored.
- A label channel such as Greyscale Records still needs the mapped tracked artist's name in the video title. Mapping Antagonist A.D. must not admit The Beautiful Monument or other label artists.
- A short teaser and a real music video can share confusing titles. Manual Hide and permanent rejection handle mistakes.
- Videos belong in the main chronological feed and standard RSS, not only in a separate videos page.
- Known channels should be scanned even if broader discovery quota is unavailable.
- Manual channel additions and suggested-channel review remain necessary because automatic discovery can find inactive or similarly named channels.
- Exclude title/tag/duration signals for Shorts, under-one-minute videos, vertical video, trailers, promos, recaps, highlights, Official Audio, visualizers, lyric videos, vlogs, and behind-the-scenes material. These exclusions override old approvals.
- The video review queue is its own collapsed management section and supports rejecting every remaining unselected candidate in one action.

### Personal controls and PWA

- Release removal is called **Hide**, never **Mute**, because Mute sounds like audio control.
- Settings backup export/import excludes credentials.
- Themes are simply Green, Red, Purple, and Grey. Red evokes YouTube; Purple is black/purple rather than a bright palette.
- DropSignal is an installable Android-first PWA with desktop/iOS support, a maskable icon, offline shell, and remembered device-local filters/theme.
- Push notifications were explicitly not required for 2.0.
- A trusted personal device should not ask for a password on every rating, hide, or settings change. Shared devices can opt out and use encrypted password unlock. Browser/PWA storage is device-local; user data itself remains GitHub-backed for cross-device consistency.

### Listening history

- Every release and music video can be rated 1-5 stars.
- Selecting a star visually fills it and every star to its left.
- Four or five stars count as Like; one, two, or three count as Dislike.
- History extends beyond the 45-day main-feed window and can search MusicBrainz for still older releases.
- It records release date and rating date and filters by sentiment, item type, and text.
- Navigating to rate an item and returning must preserve release filters.
- The UI applies ratings locally immediately rather than waiting for the Pages deployment.
- `ratings.json` provides cross-device persistence. A rapid second save can otherwise reuse a cached GitHub blob SHA, so every save must bypass cache and retry read/merge/write conflicts without dropping pending changes.

### 2.0 release

The app was named **DropSignal**. `v2.0.0` marks the PWA milestone. `v2.0.1` is the stable 2.0 handoff and adds the reliable consecutive-rating save behavior.

## UX preferences to preserve

- Dark, dense, music-focused design inspired by Spotify Release List, with restrained coloured type accents.
- Avoid sticky search/filter controls that consume screen space while scrolling.
- Multi-select category filters are required, such as Albums + EPs without Singles or Features.
- Released items default newest-first; Upcoming defaults nearest-first.
- Major management sections should be collapsed by default on mobile.
- Deselected artists are greyed out rather than presented as an ugly checklist.
- Keep controls attractive and understandable to nontechnical users.
- Exact URLs are preferred, but transparent search fallbacks are acceptable.
- Do not notify or display unreleased music in the default feed; anticipation is not the default experience.
- Avoid model/agent usage for scheduled routine work.

## Approaches rejected or deferred

- Spotify API as the primary source: Premium/auth/developer complexity and catalogue limitations were not worth it.
- Headless automation of Spotify Release List: brittle and machine-bound.
- YouTube Music subscriptions as canonical metadata: useful library signal but insufficiently structured.
- Vercel/backend rewrite: unnecessary for a personal static app.
- Central user accounts: requires a real backend and paid-project territory.
- Automatic Spotify/YouTube Music playlists: paused.
- Push notifications and notification preferences: paused.
- Calendar feed: considered unnecessary.
- New-since-last-visit markers: not needed.
- Source-health page: not useful to the user at present.

## Version 2.1 direction: concerts

Concerts are deliberately separated from the stable 2.0 release because event coverage and identity matching are less reliable than release metadata.

Agreed requirements:

- User-selectable timezone, home city, state/region, and maximum travel area.
- Jamie's initial profile is Auckland with the North Island as the maximum travel area; travel outside that area is not useful.
- Support slots count, not only headliners. Festival lineups should count too.
- Show bands, venue, locality, date/time, and direct ticket-merchant link.
- Prioritize Under The Radar for smaller New Zealand bands/shows; use Ticketmaster and possibly Live Nation/Bandsintown for larger events.
- Expect manual aliases, corrections, deduplication, and review because event artist names and ticket listings are inconsistent.

Start with a source-coverage experiment before designing the final UI. Confirm that tracked smaller artists can actually be found around Auckland/North Island and record source terms/API constraints before committing to an automated pipeline.

## Operational history worth remembering

- A conversational Hermes cron consumed an entire model allowance and produced noisy Telegram “No new releases” messages. The no-agent `hermes_job.py` wrapper and `--quiet-if-none` behavior exist specifically to prevent that.
- Website saves trigger GitHub commits and Pages rebuilds. Changes that only affect local display should be optimistic/device-local where possible; do not make the user wait for deployment before seeing a star/filter change.
- Automated Last.fm/channel synchronization can create bot commits while a human change is in progress. Always incorporate the remote tip instead of force-pushing over personal configuration.
- Workflow runs can be cancelled and replaced by a newer run. Judge deployment success from the newest commit/run.
