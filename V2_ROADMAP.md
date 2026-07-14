# Version 2 roadmap

Version 1 is permanently preserved by the `v1.0.0` Git tag. Version 2 remains a personal, GitHub-hosted application with no paid backend or multi-user accounts.

## Agreed scope

### Daily digest RSS — complete

- Publish during the listener's local 6am hour.
- Show releases expected today first.
- Follow with releases made available yesterday.
- Group each section as Albums, EPs, Singles, Features, then other releases.
- Use the timezone selected on the management page.
- Keep the existing release-by-release RSS feed.

### Music videos — next major feature

- Discover recent uploads from known artist and record-label YouTube channels.
- Recognise strong title signals such as “official”, “official video”, and “music video”.
- Support multiple channel mappings per artist, including personal channels such as Alex Terrible for Slaughter to Prevail.
- Provide a review queue for uncertain matches and remember approvals/rejections.
- Provide manual artist, label, channel, and search aliases as fallbacks.
- Keep this separate from release metadata because MusicBrainz video relationships are too incomplete to be the primary source.

### Personal controls

- Add easy release muting using the existing release-ID blacklist.
- Add export/import for tracked artists, blacklist, aliases, settings, and review decisions.
- Add selectable themes using the current design: green default, YouTube red, and black/purple.

These controls are complete. Alias management and a Last.fm unresolved-name review queue are also live; the same data model can now be extended for music-video sources and review decisions.

### Concerts — later and lowest priority

- Let the listener choose timezone, home city/region, and travel area.
- For the personal setup, Auckland is home and the North Island is the maximum travel area.
- Include support slots as well as headline appearances and festivals.
- Combine smaller-show coverage from Under The Radar with Ticketmaster coverage for larger events when practical.
- Store direct venue, date, lineup, location, and ticket links.
- Expect manual artist aliases and source corrections because event data is inconsistent.

## Explicitly deferred

- PWA installation and push notifications
- Automatic Spotify or YouTube Music playlists
- User accounts and a paid/shared backend
- Calendar feeds
- New-since-last-visit markers
- Notification preference controls

## Suggested delivery order

1. Daily digest RSS
2. Themes, release muting, and export/import
3. Alias management and the music-video review data model
4. Music-video discovery and its dedicated page
5. Concert discovery experiments, starting with Auckland/North Island coverage
