# DropSignal 2.x status and roadmap

Version 1 is permanently preserved by the `v1.0.0` Git tag. Version 2 remains a personal, GitHub-hosted application with no paid backend or multi-user accounts.

## Stable 2.0

- `v2.0.0`: DropSignal naming and installable PWA milestone.
- `v2.0.1`: current stable release, including conflict-safe consecutive rating saves.

Completed 2.0 scope:

- Timezone-aware 6am daily digest RSS, with today's expected releases before yesterday's released items.
- Existing item-by-item RSS with artwork, tracklists, and music videos.
- Official music-video tracking through known/discovered artist, personal, and label channels.
- Video title/duration exclusions, dedicated review queue, bulk rejection, Hide/restore, and main-feed integration.
- Release hiding, settings backup import/export, manual aliases, unresolved Last.fm review, and recent-favourites onboarding.
- Green, Red, Purple, and Grey device themes.
- Installable Android-first PWA with desktop/iOS support and trusted-device login.
- GitHub-synced 1-5 star listening history, older-release lookup, likes/dislikes, and remembered feed filters.

2.0 is closed except for bug fixes and small polish.

## Planned 2.1: concerts

Concerts are the next major feature and should begin as a source-coverage experiment.

Requirements:

- Let the listener choose timezone, home city/region, and maximum travel area.
- For the personal setup, Auckland is home and the North Island is the maximum travel area.
- Include tracked artists appearing as support, at festivals, or as headliners.
- Prioritize Under The Radar for smaller New Zealand shows; supplement with Ticketmaster and, where useful, Live Nation or Bandsintown.
- Store and show direct venue, date/time, lineup, locality, and ticket links.
- Deduplicate the same event across sources.
- Support manual artist/event aliases and review corrections because event metadata is inconsistent.

Before implementing a complete Concerts tab, test source coverage against a representative group of Jamie's smaller tracked artists and document authentication, rate limits, terms, and link stability.

## Explicitly deferred

- Push notifications and notification-preference controls.
- Automatic Spotify or YouTube Music playlists.
- User accounts and a paid/shared backend.
- Calendar feeds.
- New-since-last-visit markers.
- Source-health diagnostics.

Reopen deferred items only when Jamie explicitly changes their priority.
