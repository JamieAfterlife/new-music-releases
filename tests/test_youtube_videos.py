import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_video_tracker import classify_video, discover_channels, is_excluded_video_title, is_strong_artist_channel, is_topic_channel, main as video_main, render_video_page, scan_videos


class FakeYouTube:
    def __init__(self, uploads):
        self._uploads = uploads

    def channel(self, identifier):
        return {
            "id": "UCtest",
            "snippet": {"title": "Test Channel"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UUtest"}},
        }

    def uploads(self, playlist_id, limit=15):
        return self._uploads

    def recent_uploads(self, channel_id):
        return self._uploads

    def search_channels(self, artist_name, limit=3):
        return [{
            "id": {"channelId": f"UC-{artist_name}"},
            "snippet": {"channelTitle": artist_name, "description": "Official artist channel"},
        }]


class AmbiguousYouTube(FakeYouTube):
    def search_channels(self, artist_name, limit=5):
        return [{
            "id": {"channelId": f"UC-{index}"},
            "snippet": {"channelTitle": title, "description": "Possible artist channel"},
        } for index, title in enumerate(("Record Label", f"{artist_name} Archive", "Music Television", "Extra Result"), 1)]


class HandleYouTube(FakeYouTube):
    def channel(self, identifier):
        if identifier == "@needschannel":
            return {"id": "UC-handle", "snippet": {"title": "Needs Channel"}, "contentDetails": {}}
        return None

    def search_channels(self, artist_name, limit=5):
        return []


class FeedOnlyYouTube(FakeYouTube):
    def recent_uploads(self, channel_id):
        return self._uploads

    def uploads(self, playlist_id, limit=50):
        return []


def upload(video_id, title, published="2026-07-14T08:00:00Z"):
    return {
        "snippet": {
            "title": title,
            "publishedAt": published,
            "resourceId": {"videoId": video_id},
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}},
        },
        "contentDetails": {"videoId": video_id},
    }


class YouTubeVideoTests(unittest.TestCase):
    def test_artist_channel_official_video_is_automatic(self):
        status, artists, reason = classify_video(
            "New Song (Official Music Video)",
            {"kind": "artist", "artist_names": ["Slaughter to Prevail"]},
            [],
        )
        self.assertEqual(status, "auto")
        self.assertEqual(artists, ["Slaughter to Prevail"])
        self.assertIn("mapped artist channel", reason)

    def test_known_alex_terrible_video_titles_are_not_lost(self):
        source = {"kind": "artist", "artist_names": ["Slaughter to Prevail"]}
        live_video = classify_video(
            "SLAUGHTER TO PREVAIL - BEHELIT (MUSIC LIVE VIDEO January Europe tour 2026)", source, []
        )
        unclear_video = classify_video("SLAUGHTER TO PREVAIL - BABAYKA", source, [])
        self.assertEqual(live_video[0], "auto")
        self.assertEqual(unclear_video[0], "review")

    def test_audio_visualizer_lyric_and_backstage_formats_are_hard_exclusions(self):
        source = {"kind": "artist", "artist_names": ["Spiritbox"]}
        titles = [
            "Spiritbox - Song (Official Audio)",
            "Spiritbox - Song (Official Visualizer)",
            "Spiritbox - Song (Lyric Video)",
            "Spiritbox Studio Vlog",
            "Spiritbox - Behind-the-Scenes",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(is_excluded_video_title(title))
                self.assertEqual(classify_video(title, source, [])[0], "ignore")

    def test_label_channel_requires_a_tracked_artist_in_the_title(self):
        tracked = [{"name": "Spiritbox"}]
        matched = classify_video(
            "Spiritbox - New Song (Official Video)", {"kind": "label"}, tracked
        )
        uncertain = classify_video(
            "Unknown Band - New Song (Official Video)", {"kind": "label"}, tracked
        )
        self.assertEqual((matched[0], matched[1]), ("auto", ["Spiritbox"]))
        self.assertEqual(uncertain[0], "ignore")

    def test_mapped_label_only_matches_its_mapped_artist(self):
        tracked = [{"name": "Antagonist A.D."}, {"name": "The Beautiful Monument"}]
        source = {"kind": "label", "artist_names": ["Antagonist A.D."]}
        antagonist = classify_video("Antagonist AD - New Song (Official Music Video)", source, tracked)
        other_band = classify_video("The Beautiful Monument - New Song (Official Music Video)", source, tracked)
        self.assertEqual((antagonist[0], antagonist[1]), ("auto", ["Antagonist A.D."]))
        self.assertEqual((other_band[0], other_band[1]), ("ignore", []))

    def test_auto_generated_topic_channels_are_excluded(self):
        self.assertTrue(is_topic_channel({"snippet": {"channelTitle": "Spiritbox - Topic"}}))
        self.assertTrue(is_topic_channel({"snippet": {"title": "Spiritbox", "description": "Auto-generated by YouTube."}}))
        self.assertFalse(is_topic_channel({"snippet": {"channelTitle": "Spiritbox"}}))

    def test_only_unmistakable_artist_channel_names_are_automatic(self):
        self.assertTrue(is_strong_artist_channel({"snippet": {"channelTitle": "Spiritbox"}}, "Spiritbox"))
        self.assertTrue(is_strong_artist_channel({"snippet": {"channelTitle": "Spiritbox Official"}}, "Spiritbox"))
        self.assertFalse(is_strong_artist_channel({"snippet": {"channelTitle": "Spiritbox Archive"}}, "Spiritbox"))

    def test_scan_saves_published_and_review_videos(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "video_sources.json").write_text(json.dumps({"channels": [
                {"handle": "@Test", "kind": "label", "artist_names": []}
            ]}), encoding="utf-8")
            (root / "artists.json").write_text(json.dumps({"artists": [{"name": "Spiritbox"}]}), encoding="utf-8")
            fake = FakeYouTube([
                upload("auto-id", "Spiritbox - Song (Official Music Video)"),
                upload("review-id", "Spiritbox - Song Premiere", "2026-05-21T16:00:18Z"),
            ])
            found, review = scan_videos(
                root, "key", dt.datetime(2026, 7, 14, 9, tzinfo=dt.timezone.utc), fake
            )
            self.assertEqual((found, review), (1, 1))
            videos = json.loads((root / "data" / "videos.json").read_text())
            queue = json.loads((root / "data" / "video_review.json").read_text())
            self.assertIn("auto-id", videos["videos"])
            self.assertEqual(queue["videos"][0]["id"], "review-id")

    def test_recent_channel_feed_catches_video_missing_from_uploads_playlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "video_sources.json").write_text(json.dumps({"channels": [
                {"handle": "UCR7Ls5FuT6UKTcsMkcwgCUA", "kind": "artist", "artist_names": ["Mastodon"]}
            ]}), encoding="utf-8")
            (root / "artists.json").write_text(json.dumps({"artists": [{"name": "Mastodon"}]}), encoding="utf-8")
            found, review = scan_videos(
                root, "key", dt.datetime(2026, 7, 15, 9, tzinfo=dt.timezone.utc),
                FeedOnlyYouTube([upload("94Cr7eKDZbA", "Mastodon - Snakes For Dinner (Official Video)")]),
            )
            self.assertEqual((found, review), (1, 0))
            videos = json.loads((root / "data" / "videos.json").read_text())
            self.assertIn("94Cr7eKDZbA", videos["videos"])

    def test_known_channels_scan_before_noncritical_discovery_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "site.json").write_text('{"feed_title":"Test"}', encoding="utf-8")
            with patch.dict("os.environ", {"YOUTUBE_API_KEY": "key"}), patch(
                "youtube_video_tracker.scan_videos", return_value=(1, 0)
            ) as scan, patch(
                "youtube_video_tracker.discover_channels", side_effect=OSError("quota")
            ) as discover:
                result = video_main(["scan", "--root", str(root)])
            self.assertEqual(result, 0)
            scan.assert_called_once()
            discover.assert_called_once()

    def test_old_approval_cannot_publish_an_excluded_audio_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "video_sources.json").write_text(json.dumps({"channels": [
                {"handle": "@Test", "kind": "artist", "artist_names": ["Spiritbox"]}
            ]}), encoding="utf-8")
            (root / "artists.json").write_text(json.dumps({"artists": [{"name": "Spiritbox"}]}), encoding="utf-8")
            (root / "video_decisions.json").write_text(json.dumps({"approved": ["audio-id"], "rejected": []}), encoding="utf-8")
            found, review = scan_videos(
                root, "key", dt.datetime(2026, 7, 14, 9, tzinfo=dt.timezone.utc),
                FakeYouTube([upload("audio-id", "Spiritbox - Song (Official Audio)")]),
            )
            self.assertEqual((found, review), (0, 0))

    def test_channel_discovery_automatically_adds_one_strong_exact_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artists.json").write_text(json.dumps({"artists": [
                {"name": "Already Mapped", "mbid": "mapped-id"},
                {"name": "Needs Channel", "mbid": "new-id"},
            ]}), encoding="utf-8")
            (root / "video_sources.json").write_text(json.dumps({"channels": [{
                "channel_id": "UCmapped", "kind": "artist", "artist_names": ["Already Mapped"]
            }]}), encoding="utf-8")
            searched, added, pending = discover_channels(
                root, FakeYouTube([]), dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc), 40
            )
            queue = json.loads((root / "data" / "video_channel_review.json").read_text())
            sources = json.loads((root / "video_sources.json").read_text())
            self.assertEqual((searched, added, pending), (1, 1, 0))
            self.assertEqual(queue["channels"], [])
            self.assertEqual(sources["channels"][-1]["artist_names"], ["Needs Channel"])

    def test_channel_discovery_keeps_multiple_ambiguous_candidates_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artists.json").write_text(json.dumps({"artists": [
                {"name": "Needs Channel", "mbid": "new-id"},
            ]}), encoding="utf-8")
            (root / "video_sources.json").write_text('{"channels": []}', encoding="utf-8")
            (root / "data").mkdir()
            (root / "data" / "video_discovery.json").write_text(json.dumps({
                "processed_artist_mbids": ["new-id"], "daily_searches": {}
            }), encoding="utf-8")
            searched, added, pending = discover_channels(
                root, AmbiguousYouTube([]), dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc), 40
            )
            state = json.loads((root / "data" / "video_discovery.json").read_text())
            queue = json.loads((root / "data" / "video_channel_review.json").read_text())
            self.assertEqual((searched, added, pending), (1, 0, 3))
            self.assertEqual(len(queue["channels"]), 3)
            self.assertNotIn("processed_artist_mbids", state)
            self.assertIn("new-id", state["artist_last_searched"])

    def test_channel_discovery_tries_likely_handles_without_search_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artists.json").write_text(json.dumps({"artists": [
                {"name": "Needs Channel", "mbid": "new-id"},
            ]}), encoding="utf-8")
            (root / "video_sources.json").write_text('{"channels": []}', encoding="utf-8")
            searched, added, pending = discover_channels(
                root, HandleYouTube([]), dt.datetime(2026, 7, 14, tzinfo=dt.timezone.utc), 40
            )
            sources = json.loads((root / "video_sources.json").read_text())
            self.assertEqual((searched, added, pending), (0, 1, 0))
            self.assertEqual(sources["channels"][0]["channel_id"], "UC-handle")

    def test_render_creates_searchable_video_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "videos.json").write_text(json.dumps({"videos": {
                "video-id": {
                    "id": "video-id", "title": "Official Video", "channel": "Band",
                    "published_at": "2026-07-14T08:00:00Z", "thumbnail": "https://example.test/image.jpg",
                    "url": "https://www.youtube.com/watch?v=video-id", "matched_artists": ["Band"]
                }
            }}), encoding="utf-8")
            (root / "videos_template.html").write_text(Path("videos_template.html").read_text(encoding="utf-8"), encoding="utf-8")
            count = render_video_page(root, root / "public", "Test music")
            page = (root / "public" / "videos.html").read_text(encoding="utf-8")
            self.assertEqual(count, 1)
            self.assertIn("Official Video", page)
            self.assertIn("Watch on YouTube", page)
            self.assertIn("manage.html?hide_video=video-id", page)

    def test_hidden_published_video_remains_available_to_unhide(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "video_sources.json").write_text(json.dumps({"channels": [
                {"handle": "@Test", "kind": "artist", "artist_names": ["Band"]}
            ]}), encoding="utf-8")
            (root / "artists.json").write_text(json.dumps({"artists": [{"name": "Band"}]}), encoding="utf-8")
            (root / "video_decisions.json").write_text(json.dumps({"approved": [], "rejected": ["hidden-id"]}), encoding="utf-8")
            (root / "data" / "videos.json").write_text(json.dumps({"videos": {
                "hidden-id": {"id": "hidden-id", "title": "Teaser", "published_at": "2026-07-14T08:00:00Z"}
            }}), encoding="utf-8")
            scan_videos(root, "key", dt.datetime(2026, 7, 14, 9, tzinfo=dt.timezone.utc), FakeYouTube([]))
            videos = json.loads((root / "data" / "videos.json").read_text(encoding="utf-8"))
            self.assertIn("hidden-id", videos["videos"])

    def test_scan_removes_legacy_topic_channel_videos(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "video_sources.json").write_text('{"channels": []}', encoding="utf-8")
            (root / "artists.json").write_text('{"artists": []}', encoding="utf-8")
            (root / "data" / "videos.json").write_text(json.dumps({"videos": {
                "topic-id": {"id": "topic-id", "channel": "Band - Topic", "published_at": "2026-07-14T08:00:00Z"}
            }}), encoding="utf-8")
            scan_videos(root, "key", dt.datetime(2026, 7, 14, 9, tzinfo=dt.timezone.utc), FakeYouTube([]))
            videos = json.loads((root / "data" / "videos.json").read_text(encoding="utf-8"))
            self.assertNotIn("topic-id", videos["videos"])


if __name__ == "__main__":
    unittest.main()
