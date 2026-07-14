import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from youtube_video_tracker import classify_video, render_video_page, scan_videos


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

    def test_label_channel_requires_artist_name_or_review(self):
        tracked = [{"name": "Spiritbox"}]
        matched = classify_video(
            "Spiritbox - New Song (Official Video)", {"kind": "label"}, tracked
        )
        uncertain = classify_video(
            "Unknown Band - New Song (Official Video)", {"kind": "label"}, tracked
        )
        self.assertEqual((matched[0], matched[1]), ("auto", ["Spiritbox"]))
        self.assertEqual(uncertain[0], "review")

    def test_scan_saves_published_and_review_videos(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "video_sources.json").write_text(json.dumps({"channels": [
                {"handle": "@Test", "kind": "label", "artist_names": []}
            ]}), encoding="utf-8")
            (root / "artists.json").write_text(json.dumps({"artists": [{"name": "Spiritbox"}]}), encoding="utf-8")
            fake = FakeYouTube([
                upload("auto-id", "Spiritbox - Song (Official Music Video)"),
                upload("review-id", "Unknown Band - Song (Official Video)"),
            ])
            found, review = scan_videos(
                root, "key", dt.datetime(2026, 7, 14, 9, tzinfo=dt.timezone.utc), fake
            )
            self.assertEqual((found, review), (1, 1))
            videos = json.loads((root / "data" / "videos.json").read_text())
            queue = json.loads((root / "data" / "video_review.json").read_text())
            self.assertIn("auto-id", videos["videos"])
            self.assertEqual(queue["videos"][0]["id"], "review-id")

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


if __name__ == "__main__":
    unittest.main()
