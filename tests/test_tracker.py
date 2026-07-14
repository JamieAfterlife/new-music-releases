import datetime as dt
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music_release_tracker import (
    MusicBrainz,
    Settings,
    VARIOUS_ARTISTS_MBID,
    add_artist,
    artist_blacklist_reason,
    blacklist_reason,
    build_recent_lastfm_candidates,
    fallback_links,
    is_compilation_demo_appearance,
    is_various_artists,
    make_rss,
    make_html,
    make_history_html,
    make_manage_html,
    main,
    import_csv,
    import_lastfm,
    comparable_date,
    digest_due,
    display_time,
    display_release_type,
    make_digest_rss,
    normalize_release,
    notification_markdown,
    release_description,
    run_check,
    visible_releases,
)


ARTIST = {"name": "Test Artist", "mbid": "11111111-1111-1111-1111-111111111111"}


def group(rgid="22222222-2222-2222-2222-222222222222", artist_id=None, secondary=None):
    return {
        "id": rgid,
        "title": "A Night Outside",
        "first-release-date": "2026-07-12",
        "primary-type": "EP",
        "secondary-types": secondary or ["Live"],
        "artist-credit": [{"artist": {"id": artist_id or ARTIST["mbid"], "name": "Test Artist"}}],
    }


class FakeMusicBrainz:
    def __init__(self, groups):
        self.groups = groups

    def release_groups(self, mbid, start, end):
        return list(self.groups)

    def appearance_groups(self, mbid, start, end):
        return []

    def release_group_links(self, mbid):
        return [
            {"url": {"resource": "https://open.spotify.com/album/exact"}},
            {"url": {"resource": "https://music.youtube.com/playlist?list=exact"}},
        ]

    def release_group_metadata(self, mbid, release_date=""):
        return {
            "relations": self.release_group_links(mbid),
            "edition_id": "edition-exact",
            "tracklist": [
                {"disc": 1, "disc_title": "", "position": "1", "title": "First Track", "length_ms": 185000}
            ],
        }

    def search_artists(self, name, limit=5):
        return [{"id": f"mbid-{name}", "name": name, "score": 100}]


class TrackerTests(unittest.TestCase):
    def test_github_notification_contains_playable_links(self):
        release = normalize_release(group(), ARTIST)
        release["links"] = {"spotify": "https://open.spotify.com/album/exact"}
        message = notification_markdown([release])
        self.assertIn("Test Artist — A Night Outside", message)
        self.assertIn("[Spotify](https://open.spotify.com/album/exact)", message)
        self.assertIn("[YouTube Music]", message)

    def test_explicit_timezone_is_stable_on_github(self):
        instant = dt.datetime(2026, 7, 14, 0, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(display_time(instant, "Pacific/Auckland").strftime("%H:%M %Z"), "12:00 NZST")
        self.assertEqual(display_time(instant, "Not/AZone").tzinfo, dt.timezone.utc)

    def test_artist_blacklist_prevents_reimport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.blacklist_file = root / "blacklist.json"
            settings.blacklist_file.write_text(
                json.dumps({"artists": [ARTIST["name"]], "artist_mbids": [ARTIST["mbid"]]}),
                encoding="utf-8",
            )
            self.assertEqual(
                artist_blacklist_reason(ARTIST["name"], ARTIST["mbid"], json.loads(settings.blacklist_file.read_text())),
                "artist name",
            )
            with self.assertRaisesRegex(ValueError, "blocked"):
                add_artist(settings, FakeMusicBrainz([]), ARTIST["name"], ARTIST["mbid"])

    def test_manage_page_embeds_artist_toggle_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.blacklist_file = root / "blacklist.json"
            settings.watchlist.write_text(json.dumps({"artists": [ARTIST]}), encoding="utf-8")
            settings.blacklist_file.write_text(
                json.dumps({"artists": [], "artist_mbids": [], "release_ids": [], "title_contains": []}),
                encoding="utf-8",
            )
            page = make_manage_html(settings)
            self.assertIn("Manage tracked artists", page)
            self.assertIn(ARTIST["name"], page)
            self.assertIn("artist--tracked", page)

    def test_manage_page_embeds_release_muting_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            settings.state_file = root / "data" / "state.json"
            settings.blacklist_file = root / "blacklist.json"
            settings.state_file.parent.mkdir()
            settings.state_file.write_text(
                json.dumps({"releases": {"release-id": {
                    "title": "A Release", "artist": "An Artist", "date": "2026-07-14"
                }}}),
                encoding="utf-8",
            )
            settings.blacklist_file.write_text(
                json.dumps({"artists": [], "artist_mbids": [], "release_ids": ["release-id"]}),
                encoding="utf-8",
            )
            page = make_manage_html(settings)
            self.assertIn("Hidden releases", page)
            self.assertIn("Show again", page)
            self.assertIn("A Release", page)
            self.assertIn("Export backup", page)
            self.assertIn("GitHub tokens are never included", page)
            self.assertNotIn("__RELEASES_JSON__", page)

    def test_manage_page_embeds_alias_review_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            (root / "data").mkdir()
            (root / "aliases.json").write_text(json.dumps({"artist_aliases": [{
                "source_name": "Odd Last.fm Name", "name": "Correct Artist", "mbid": "correct-id"
            }]}), encoding="utf-8")
            (root / "data" / "lastfm_unresolved.json").write_text(
                json.dumps({"artists": [{"source_name": "Needs Review"}]}), encoding="utf-8"
            )
            page = make_manage_html(settings)
            self.assertIn("Artist name fixes", page)
            self.assertIn("Odd Last.fm Name", page)
            self.assertIn("Needs Review", page)
            self.assertNotIn("__ALIASES_JSON__", page)
            self.assertNotIn("__UNRESOLVED_JSON__", page)
            self.assertNotIn("__VIDEO_SOURCES_JSON__", page)
            self.assertNotIn("__VIDEO_REVIEW_JSON__", page)
            self.assertNotIn("__VIDEO_CHANNEL_REVIEW_JSON__", page)

    def test_management_sections_collapse_and_release_credits_can_be_ignored(self):
        template = Path("manage_template.html").read_text(encoding="utf-8")
        self.assertGreaterEqual(template.count('<details class="card">'), 8)
        self.assertIn("Ignore credit", template)
        self.assertIn("ignored_sources", template)
        self.assertIn('details.card[open] > summary::after', template)
        self.assertIn('<summary class="summary"><div><h2>Video review queue</h2>', template)
        self.assertIn('id="reject-all-videos"', template)
        self.assertIn("Reject all ${pending.length} remaining video", template)

    def test_artist_name_fix_search_stays_in_its_own_section(self):
        template = Path("manage_template.html").read_text(encoding="utf-8")
        self.assertIn('id="alias-query"', template)
        self.assertIn('id="alias-results"', template)
        self.assertIn("async function searchAlias()", template)
        self.assertNotIn("el('query').scrollIntoView", template)

    def test_personal_devices_can_reconnect_without_a_password(self):
        manage = Path("manage_template.html").read_text(encoding="utf-8")
        history = Path("history_template.html").read_text(encoding="utf-8")
        helper = Path("device_auth.js").read_text(encoding="utf-8")
        for page in (manage, history):
            self.assertIn('id="trust-device"', page)
            self.assertIn('src="device-auth.js?v=4"', page)
            self.assertIn("autoConnectTrusted()", page)
            self.assertIn("DeviceAuth.loadSession(connectionKey)", page)
            self.assertIn("DeviceAuth.saveSession(connectionKey", page)
        self.assertIn("indexedDB.open", helper)
        self.assertIn("trusted-v2", helper)
        self.assertIn("localStorage.setItem", helper)
        self.assertIn("exportKey('raw'", helper)
        self.assertIn("sessionStorage.setItem", helper)
        self.assertIn("el('trust-device').checked = true", manage)
        self.assertIn("el('trust-device').checked=true", history)

    def test_site_templates_include_device_themes(self):
        web = Path("web_template.html").read_text(encoding="utf-8")
        manage = Path("manage_template.html").read_text(encoding="utf-8")
        history = Path("history_template.html").read_text(encoding="utf-8")
        videos = Path("videos_template.html").read_text(encoding="utf-8")
        for page in (web, manage, history, videos):
            self.assertIn("release-theme", page)
            self.assertIn('data-theme="youtube"', page)
            self.assertIn('data-theme="purple"', page)
            self.assertIn('data-theme="grey"', page)
        self.assertIn('>Red</option>', web)
        self.assertIn('>Purple</option>', manage)
        self.assertIn('>Grey</option>', manage)

    def test_release_filters_allow_multiple_categories(self):
        template = Path("web_template.html").read_text(encoding="utf-8")
        self.assertIn("const activeFilters = new Set()", template)
        self.assertIn("activeFilters.has(filter)", template)
        self.assertIn("selectedCategories.some", template)
        self.assertNotIn("let active = 'all'", template)

    def test_manage_page_embeds_recent_lastfm_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.blacklist_file = root / "blacklist.json"
            settings.watchlist.write_text(json.dumps({"artists": []}), encoding="utf-8")
            (root / "data").mkdir()
            (root / "data" / "lastfm_recent_artists.json").write_text(
                json.dumps({"minimum_scrobbles": 5, "artists": [{
                    **ARTIST,
                    "lastfm_scrobbles_12month": 7,
                    "lastfm_user": "listener",
                }]}),
                encoding="utf-8",
            )
            page = make_manage_html(settings)
            self.assertIn("Don’t miss your recent favourites", page)
            self.assertIn("lastfm_scrobbles_12month", page)
            self.assertNotIn("__RECENT_LASTFM_JSON__", page)

    def test_manage_page_encrypts_restricted_github_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            page = make_manage_html(settings)
            self.assertIn("localStorage.setItem(connectionKey", page)
            self.assertIn("Forget saved token", page)
            self.assertIn("crypto.subtle.encrypt", page)
            self.assertIn("crypto.subtle.decrypt", page)
            self.assertIn("iterations:250000", page)
            self.assertNotIn("token:el('token')", page)

    def test_recent_lastfm_candidates_use_twelve_month_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            rows = [
                {"name": "Recent Favourite", "mbid": "recent-mbid", "playcount": "7"},
                {"name": "Too Occasional", "mbid": "rare-mbid", "playcount": "4"},
            ]
            with patch("music_release_tracker.fetch_lastfm_top_artists", return_value=rows):
                candidates, unresolved = build_recent_lastfm_candidates(
                    settings, FakeMusicBrainz([]), "listener", "key", 5
                )
            self.assertEqual((len(candidates), unresolved), (1, []))
            self.assertEqual(candidates[0]["lastfm_scrobbles_12month"], 7)
            saved = json.loads((root / "data" / "lastfm_recent_artists.json").read_text())
            self.assertEqual(saved["period"], "12month")

    def test_custom_alias_resolves_future_lastfm_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.blacklist_file = root / "blacklist.json"
            (root / "aliases.json").write_text(json.dumps({"artist_aliases": [{
                "source_name": "Odd Last.fm Name", "name": "Correct Artist", "mbid": "correct-id"
            }]}), encoding="utf-8")
            with patch("music_release_tracker.fetch_lastfm_artists", return_value=[{
                "name": "Odd Last.fm Name", "mbid": "", "playcount": "12"
            }]):
                processed, unresolved, total = import_lastfm(
                    settings, FakeMusicBrainz([]), "listener", "key", 5
                )
            self.assertEqual((processed, unresolved, total), (1, [], 1))
            saved = json.loads(settings.watchlist.read_text(encoding="utf-8"))
            self.assertEqual(saved["artists"][0]["mbid"], "correct-id")
            self.assertEqual(saved["artists"][0]["name"], "Correct Artist")

    def test_ignored_lastfm_release_credit_is_not_requested_as_an_artist_fix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.blacklist_file = root / "blacklist.json"
            credit = "Poppy, Amy Lee & Courtney LaPlante"
            (root / "aliases.json").write_text(json.dumps({
                "artist_aliases": [], "ignored_sources": [credit]
            }), encoding="utf-8")
            with patch("music_release_tracker.fetch_lastfm_artists", return_value=[{
                "name": credit, "mbid": "", "playcount": "12"
            }]):
                processed, unresolved, total = import_lastfm(
                    settings, FakeMusicBrainz([]), "listener", "key", 5
                )
            self.assertEqual((processed, unresolved, total), (0, [], 1))
            self.assertEqual(json.loads(settings.watchlist.read_text(encoding="utf-8"))["artists"], [])

    def test_star_rating_highlights_every_star_to_the_left(self):
        web = Path("web_template.html").read_text(encoding="utf-8")
        history = Path("history_template.html").read_text(encoding="utf-8")
        self.assertIn(":has(~ .rating__star:hover)", web)
        self.assertIn(":has(~ .star:hover)", history)
        self.assertIn("index<number", history)

    def test_metadata_prefers_complete_same_day_digital_edition(self):
        class EditionMusicBrainz(MusicBrainz):
            def __init__(self):
                pass

            def get(self, entity, params, retries=4):
                def edition(edition_id, track_count, date="2026-07-12"):
                    return {
                        "id": edition_id,
                        "status": "Official",
                        "country": "XW",
                        "date": date,
                        "media": [{
                            "position": 1,
                            "format": "Digital Media",
                            "tracks": [
                                {"position": index, "title": f"Track {index}"}
                                for index in range(1, track_count + 1)
                            ],
                        }],
                        "relations": [],
                    }

                return {"releases": [edition("standard", 10), edition("deluxe", 14)]}

        metadata = EditionMusicBrainz().release_group_metadata("release-group", "2026-07-12")
        self.assertEqual(metadata["edition_id"], "deluxe")
        self.assertEqual(len(metadata["tracklist"]), 14)

    def test_upcoming_release_is_shown_then_notified_on_release_day(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artists.json").write_text(json.dumps({"artists": [ARTIST]}), encoding="utf-8")
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.state_file = root / "data/state.json"
            settings.output_dir = root / "public"
            settings.include_appearances = False
            future = group()
            future["first-release-date"] = "2026-07-12"

            announced, current = run_check(
                settings,
                FakeMusicBrainz([future]),
                dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc),
            )
            page = (root / "public/index.html").read_text(encoding="utf-8")
            feed = (root / "public/feed.xml").read_text(encoding="utf-8")
            self.assertEqual((announced, current), ([], 1))
            self.assertIn('data-upcoming="true"', page)
            self.assertIn("Upcoming", page)
            self.assertNotIn(future["title"], feed)

            released, current = run_check(
                settings,
                FakeMusicBrainz([future]),
                dt.datetime(2026, 7, 12, tzinfo=dt.timezone.utc),
            )
            self.assertEqual((len(released), current), (1, 1))
            state = json.loads(settings.state_file.read_text(encoding="utf-8"))
            self.assertTrue(state["releases"][future["id"]]["notified_released"])

    def test_blacklist_matches_artist_release_and_title(self):
        release = normalize_release(group(), ARTIST)
        release["watched_artist_id"] = ARTIST["mbid"]
        self.assertEqual(blacklist_reason(release, {"artists": ["Test Artist"]}), "artist name")
        self.assertEqual(blacklist_reason(release, {"release_ids": [release["id"]]}), "release ID")
        self.assertEqual(blacklist_reason(release, {"title_contains": ["night out"]}), 'title contains "night out"')
        self.assertIsNone(blacklist_reason(release, {"artists": ["Someone Else"]}))

    def test_lastfm_rows_for_same_artist_are_combined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            rows = [
                {"name": "Old Name", "mbid": "same-mbid", "playcount": "75"},
                {"name": "New Name", "mbid": "same-mbid", "playcount": "125"},
            ]
            with patch("music_release_tracker.fetch_lastfm_artists", return_value=rows):
                added, unresolved, total = import_lastfm(
                    settings, FakeMusicBrainz([]), "listener", "key", 50
                )
            artists = json.loads(settings.watchlist.read_text(encoding="utf-8"))["artists"]
            self.assertEqual((added, unresolved, total), (2, [], 2))
            self.assertEqual(artists[0]["lastfm_scrobbles"], 200)

    def test_recording_search_distinguishes_primary_release_from_appearance(self):
        class RecordingSearch(MusicBrainz):
            def __init__(self):
                pass

            def _search_all(self, entity, query, key):
                self.assert_query = (entity, query, key)
                return [{
                    "id": "matched-recording",
                    "title": "Matched Song",
                    "releases": [
                        {
                            "title": "Primary",
                            "date": "2026-07-12",
                            "artist-credit": [{"artist": {"id": ARTIST["mbid"], "name": "Test Artist"}}],
                            "release-group": {"id": "primary", "primary-type": "Single"},
                        },
                        {
                            "title": "Guest Spot",
                            "date": "2026-07-12",
                            "artist-credit": [{"artist": {"id": "another-artist", "name": "Another Artist"}}],
                            "release-group": {"id": "appearance", "primary-type": "Album"},
                        },
                    ]
                }]

        groups = {item["id"]: item for item in RecordingSearch().appearance_groups(
            ARTIST["mbid"], "2026-06-01", "2026-07-21"
        )}
        self.assertFalse(groups["primary"]["appearance"])
        self.assertTrue(groups["appearance"]["appearance"])
        self.assertEqual(groups["appearance"]["appearance_track_count"], 1)
        appearance = normalize_release(groups["appearance"], ARTIST)
        self.assertEqual(display_release_type(appearance), "Single")

    def test_multi_track_appearance_keeps_album_type(self):
        item = group()
        item["primary-type"] = "Album"
        item["appearance"] = True
        item["appearance_track_count"] = 2
        release = normalize_release(item, ARTIST)
        self.assertEqual(display_release_type(release), "Album")

    def test_native_ep_and_live_classification(self):
        release = normalize_release(group(), ARTIST)
        self.assertEqual(release["type"], "EP")
        self.assertTrue(release["live"])

    def test_various_artists_filter(self):
        release = normalize_release(group(artist_id=VARIOUS_ARTISTS_MBID), ARTIST)
        release["artist"] = "Various Artists"
        self.assertTrue(is_various_artists(release))

    def test_compilation_demo_appearance_is_hidden(self):
        release = normalize_release(group(secondary=["Compilation", "Demo"]), ARTIST)
        release["artist"] = "Lamorn"
        release["appearance"] = True
        settings = Settings(root=Path("."), lookback_days=30)
        now = dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc)
        self.assertTrue(is_compilation_demo_appearance(release))
        self.assertEqual(visible_releases(settings, [release], now), [])

        release["secondary_types"] = ["Compilation"]
        self.assertFalse(is_compilation_demo_appearance(release))
        self.assertEqual(len(visible_releases(settings, [release], now)), 1)

    def test_appearance_explains_which_tracked_artist_matched(self):
        release = normalize_release(group(), ARTIST)
        release["artist"] = "Guest Artist"
        release["appearance"] = True
        self.assertIn("Matched via Test Artist", notification_markdown([release]))
        self.assertIn("Matched via Test Artist", release_description(release))

    def test_search_fallbacks_are_present(self):
        release = normalize_release(group(), ARTIST)
        links = fallback_links(release)
        self.assertIn("open.spotify.com/search/", links["spotify_search"])
        self.assertIn("music.youtube.com/search", links["youtube_music_search"])

    def test_partial_dates_are_normalized_for_bounds(self):
        self.assertEqual(comparable_date("2026"), "2026-01-01")
        self.assertEqual(comparable_date("2026-07"), "2026-07-01")
        self.assertEqual(comparable_date("2026-07-14"), "2026-07-14")

    def test_check_persists_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artists.json").write_text(json.dumps({"artists": [ARTIST]}), encoding="utf-8")
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.state_file = root / "data/state.json"
            settings.output_dir = root / "public"
            settings.include_appearances = False
            now = dt.datetime(2026, 7, 14, 0, tzinfo=dt.timezone.utc)
            first = run_check(settings, FakeMusicBrainz([group()]), now)
            second = run_check(settings, FakeMusicBrainz([group()]), now + dt.timedelta(hours=12))
            self.assertEqual((len(first[0]), first[1]), (1, 1))
            self.assertEqual((len(second[0]), second[1]), (0, 1))
            self.assertTrue((root / "public/feed.xml").exists())
            self.assertTrue((root / "public/index.html").exists())
            self.assertTrue((root / "public/history.html").exists())

    def test_primary_credit_wins_when_appearance_search_overlaps(self):
        class OverlappingMusicBrainz(FakeMusicBrainz):
            def appearance_groups(self, mbid, start, end):
                duplicate = group()
                duplicate["appearance"] = True
                return [duplicate]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artists.json").write_text(json.dumps({"artists": [ARTIST]}), encoding="utf-8")
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.state_file = root / "data/state.json"
            settings.output_dir = root / "public"
            new_releases, _ = run_check(
                settings,
                OverlappingMusicBrainz([group()]),
                dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc),
            )
            self.assertFalse(new_releases[0]["appearance"])

    def test_lastfm_threshold_does_not_disable_spotify_artist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artists = [
                {**ARTIST, "lastfm_scrobbles": 10},
                {
                    "name": "Also Spotify",
                    "mbid": "33333333-3333-3333-3333-333333333333",
                    "lastfm_scrobbles": 10,
                    "spotify_id": "spotify",
                },
            ]
            (root / "artists.json").write_text(json.dumps({"artists": artists}), encoding="utf-8")
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.state_file = root / "data/state.json"
            settings.output_dir = root / "public"
            settings.include_appearances = False
            settings.min_lastfm_scrobbles = 50
            run_check(
                settings,
                FakeMusicBrainz([group()]),
                dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc),
            )
            state = json.loads(settings.state_file.read_text(encoding="utf-8"))
            self.assertEqual(len(state["releases"]), 1)

    def test_lastfm_threshold_does_not_disable_manually_selected_artist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artist = {**ARTIST, "lastfm_scrobbles": 7, "manual_tracking": True}
            (root / "artists.json").write_text(json.dumps({"artists": [artist]}), encoding="utf-8")
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.state_file = root / "data/state.json"
            settings.output_dir = root / "public"
            settings.include_appearances = False
            settings.min_lastfm_scrobbles = 50
            run_check(
                settings,
                FakeMusicBrainz([group()]),
                dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc),
            )
            state = json.loads(settings.state_file.read_text(encoding="utf-8"))
            self.assertEqual(len(state["releases"]), 1)

    def test_incremental_check_scans_only_selected_artist(self):
        class CountingMusicBrainz(FakeMusicBrainz):
            def __init__(self):
                super().__init__([])
                self.scanned = []

            def release_groups(self, mbid, start, end):
                self.scanned.append(mbid)
                return [group(rgid=f"release-{mbid}", artist_id=mbid)]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            second = {"name": "Second Artist", "mbid": "second-mbid"}
            (root / "artists.json").write_text(
                json.dumps({"artists": [ARTIST, second]}), encoding="utf-8"
            )
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            settings.state_file = root / "data/state.json"
            settings.output_dir = root / "public"
            settings.include_appearances = False
            mb = CountingMusicBrainz()
            run_check(
                settings,
                mb,
                dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc),
                artist_mbids={second["mbid"]},
            )
            self.assertEqual(mb.scanned, [second["mbid"]])
            state = json.loads(settings.state_file.read_text(encoding="utf-8"))
            self.assertEqual(set(state["releases"]), {"release-second-mbid"})

    def test_changed_artists_command_lists_only_new_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "previous.json"
            previous.write_text(json.dumps({"artists": [ARTIST]}), encoding="utf-8")
            new_artist = {"name": "New Artist", "mbid": "new-mbid"}
            (root / "artists.json").write_text(
                json.dumps({"artists": [ARTIST, new_artist]}), encoding="utf-8"
            )
            output = io.StringIO()
            with patch("sys.stdout", output):
                result = main(["--config", str(root / "config.toml"), "changed-artists", str(previous)])
            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue().strip(), "new-mbid")

    def test_state_count_reports_missing_and_saved_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            with patch("sys.stdout", output):
                main(["--config", str(root / "config.toml"), "state-count"])
            self.assertEqual(output.getvalue().strip(), "0")
            (root / "data").mkdir()
            (root / "data" / "state.json").write_text(
                json.dumps({"releases": {"one": {}, "two": {}}}), encoding="utf-8"
            )
            output = io.StringIO()
            with patch("sys.stdout", output):
                main(["--config", str(root / "config.toml"), "state-count"])
            self.assertEqual(output.getvalue().strip(), "2")

    def test_rss_contains_release_identity(self):
        release = normalize_release(group(), ARTIST)
        release.update({
            "links": {},
            "first_seen": "2026-07-14T00:00:00+00:00",
            "tracklist": [
                {"disc": 1, "disc_title": "", "position": "1", "title": "First Track", "length_ms": 185000}
            ],
        })
        settings = Settings(root=Path("."))
        xml = make_rss(settings, [release], dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc))
        self.assertIn("musicbrainz:release-group:", xml)
        self.assertIn("YouTube Music", xml)
        self.assertIn("media:thumbnail", xml)
        self.assertIn("First Track", xml)
        self.assertIn("3:05", xml)

    def test_music_video_appears_in_main_page_and_standard_rss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "videos.json").write_text(json.dumps({"videos": {
                "video-id": {
                    "id": "video-id", "title": "Song (Official Music Video)", "channel": "Band",
                    "published_at": "2026-07-14T08:00:00Z", "thumbnail": "https://example.test/video.jpg",
                    "url": "https://www.youtube.com/watch?v=video-id", "matched_artists": ["Band"]
                },
                "audio-id": {
                    "id": "audio-id", "title": "Song (Official Audio)", "channel": "Band",
                    "published_at": "2026-07-14T07:00:00Z", "thumbnail": "https://example.test/audio.jpg",
                    "url": "https://www.youtube.com/watch?v=audio-id", "matched_artists": ["Band"]
                }
            }}), encoding="utf-8")
            settings = Settings(root=root, site_url="https://example.test")
            generated = dt.datetime(2026, 7, 14, 9, tzinfo=dt.timezone.utc)
            page = make_html(settings, [], generated)
            xml = make_rss(settings, [], generated)
            history = make_history_html(settings, [], generated)
            self.assertIn('data-type="video"', page)
            self.assertIn("Song (Official Music Video)", page)
            self.assertIn("manage.html?hide_video=video-id", page)
            self.assertIn("youtube:video:video-id", xml)
            self.assertIn("(Music Video)", xml)
            self.assertNotIn("Official Audio", page)
            self.assertNotIn("youtube:video:audio-id", xml)
            self.assertNotIn("Official Audio", history)

    def test_ratings_link_feed_items_to_synced_listening_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = normalize_release(group(), ARTIST)
            release.update({"links": {}, "first_seen": "2026-07-14T00:00:00+00:00"})
            rating_id = f'release:{release["id"]}'
            (root / "ratings.json").write_text(json.dumps({"ratings": {
                rating_id: {"rating": 5, "rated_at": "2026-07-15T01:00:00Z"}
            }}), encoding="utf-8")
            settings = Settings(root=root)
            generated = dt.datetime(2026, 7, 15, 2, tzinfo=dt.timezone.utc)
            page = make_html(settings, [release], generated)
            history = make_history_html(settings, [release], generated)
            self.assertIn('data-rating="5"', page)
            self.assertIn("history.html?rate=release%3A", page)
            self.assertIn("Listening history", page)
            self.assertIn("Liked", history)
            self.assertIn("Disliked", history)
            self.assertIn("Newest release", history)
            self.assertIn(rating_id, history)
            self.assertIn(release["date"], history)
            self.assertIn("Search MusicBrainz", history)
            self.assertIn("/ws/2/release-group?query=", history)
            old_release = {**release, "id": "old-release", "date": "2025-09-04"}
            old_history = make_history_html(settings, [old_release], generated)
            self.assertIn('"release:old-release"', old_history)
            upcoming = {**release, "id": "future-release", "upcoming": True, "date": "2026-08-01"}
            upcoming_page = make_html(settings, [upcoming], generated)
            upcoming_history = make_history_html(settings, [upcoming], generated)
            self.assertNotIn("release%3Afuture-release", upcoming_page)
            self.assertNotIn('"release:future-release"', upcoming_history)

    def test_daily_digest_starts_with_today_then_yesterday(self):
        settings = Settings(root=Path("."), timezone="UTC", site_url="https://example.test")
        today = normalize_release(group("today"), ARTIST)
        today.update({"date": "2026-07-14", "type": "Album", "links": {}})
        yesterday = normalize_release(group("yesterday"), ARTIST)
        yesterday.update({"date": "2026-07-13", "type": "EP", "links": {}})
        generated = dt.datetime(2026, 7, 14, 6, 30, tzinfo=dt.timezone.utc)
        xml = make_digest_rss(settings, [today, yesterday], generated)
        self.assertIn("new-music-digest:2026-07-14", xml)
        self.assertLess(xml.index("Expected today"), xml.index("Made available yesterday"))
        self.assertLess(xml.index("Albums"), xml.index("EPs"))
        self.assertIn("digest.xml", xml)

    def test_daily_digest_waits_until_six_in_the_selected_timezone(self):
        settings = Settings(root=Path("."), timezone="Pacific/Auckland")
        release = normalize_release(group("today"), ARTIST)
        release.update({"date": "2026-07-14", "type": "Album", "links": {}})
        before_six = dt.datetime(2026, 7, 13, 17, 30, tzinfo=dt.timezone.utc)
        at_six = dt.datetime(2026, 7, 13, 18, 30, tzinfo=dt.timezone.utc)
        self.assertNotIn("new-music-digest:2026-07-14", make_digest_rss(settings, [release], before_six))
        self.assertIn("new-music-digest:2026-07-14", make_digest_rss(settings, [release], at_six))
        self.assertFalse(digest_due(settings, before_six))
        self.assertTrue(digest_due(settings, at_six))

    def test_csv_import_preserves_comma_name_and_splits_proven_collaboration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "releases.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Artists", "Artist IDs"])
                writer.writerow(["nothing,nowhere.", "spotify-one"])
                writer.writerow(["BABYMETAL,Poppy", "spotify-two,spotify-three"])
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            added, unresolved = import_csv(settings, FakeMusicBrainz([]), source)
            artists = json.loads(settings.watchlist.read_text(encoding="utf-8"))["artists"]
            self.assertEqual(added, 3)
            self.assertEqual(unresolved, [])
            self.assertEqual({x["name"] for x in artists}, {"nothing,nowhere.", "BABYMETAL", "Poppy"})

    def test_csv_import_honors_play_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "lastfm.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Artists", "Scrobbles"])
                writer.writerow(["Frequent Artist", "1,234 scrobbles"])
                writer.writerow(["Accidental Artist", "2 scrobbles"])
            settings = Settings(root=root)
            settings.watchlist = root / "artists.json"
            added, unresolved = import_csv(settings, FakeMusicBrainz([]), source, min_plays=20)
            artists = json.loads(settings.watchlist.read_text(encoding="utf-8"))["artists"]
            self.assertEqual(added, 1)
            self.assertEqual(unresolved, [])
            self.assertEqual([x["name"] for x in artists], ["Frequent Artist"])


if __name__ == "__main__":
    unittest.main()
    blacklist_reason,
