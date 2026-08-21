import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "pyUltroid" / "fns" / "ytdl_core"


def load_core():
    name = "boudyos_test_ytdl_core"
    spec = importlib.util.spec_from_file_location(
        name,
        CORE / "__init__.py",
        submodule_search_locations=[str(CORE)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load_core()


class URLTests(unittest.TestCase):
    def test_extracts_http_url_and_trims_message_punctuation(self):
        self.assertEqual(
            core.extract_media_url(".yt see https://youtu.be/abc)."),
            "https://youtu.be/abc",
        )

    def test_rejects_missing_non_http_and_credential_urls(self):
        for value in (".yt", "ftp://example.com/a", "https://u:p@example.com/a"):
            with self.subTest(value=value), self.assertRaises(core.URLValidationError):
                core.extract_media_url(value)


class FormatTests(unittest.TestCase):
    def test_practical_resolutions_and_audio_are_not_size_filtered(self):
        metadata = {
            "formats": [
                {
                    "height": 2160,
                    "vcodec": "av01",
                    "acodec": "none",
                    "ext": "webm",
                    "filesize": 9_000_000_000,
                },
                {
                    "height": 1080,
                    "vcodec": "h264",
                    "acodec": "none",
                    "ext": "mp4",
                    "filesize": 2_000_000_000,
                },
                {"height": 1440, "vcodec": "vp9", "acodec": "none"},
                {"height": 720, "vcodec": "h264", "acodec": "none"},
                {"height": 480, "vcodec": "h264", "acodec": "none"},
                {"height": 360, "vcodec": "h264", "acodec": "none"},
                {
                    "vcodec": "none",
                    "acodec": "aac",
                    "ext": "m4a",
                    "filesize": 100_000_000,
                },
            ]
        }
        choices = core.build_format_choices(metadata)
        keys = [item.key for item in choices]
        labels = [item.label for item in choices]
        self.assertEqual(
            keys,
            [
                "best",
                "2160p",
                "1440p",
                "1080p",
                "720p",
                "480p",
                "360p",
                "audio-m4a",
                "audio-mp3",
            ],
        )
        self.assertNotIn("best_under_limit", keys)
        self.assertFalse(any("under" in label.lower() for label in labels))
        self.assertIn("ext=mp4", choices[1].selector)
        self.assertIn("ext=m4a", choices[1].selector)

    def test_choices_are_deduplicated(self):
        choices = core.build_format_choices({"formats": []})
        self.assertEqual(
            [item.key for item in choices], ["best", "audio-m4a", "audio-mp3"]
        )

    def test_only_metadata_backed_resolution_labels_are_shown(self):
        choices = core.build_format_choices(
            {"formats": [{"height": 1080, "vcodec": "h264", "acodec": "none"}]}
        )
        keys = [item.key for item in choices]
        self.assertIn("1080p", keys)
        self.assertNotIn("1440p", keys)
        self.assertNotIn("720p", keys)


class TimestampTests(unittest.TestCase):
    def test_supported_forms(self):
        self.assertEqual(core.parse_timestamp_ranges("full", 300), [])
        self.assertEqual(
            core.parse_timestamp_ranges("90-2:00", 300),
            [core.TimeRange(90, 120)],
        )
        self.assertEqual(
            core.parse_timestamp_ranges("1:00-2:00, 3:00-", 300),
            [core.TimeRange(60, 120), core.TimeRange(180, 300)],
        )
        self.assertEqual(
            core.parse_timestamp_ranges("first 60s", 300),
            [core.TimeRange(0, 60)],
        )
        self.assertEqual(
            core.parse_timestamp_ranges("last 30s", 300),
            [core.TimeRange(270, 300)],
        )

    def test_rejects_bad_inverted_duplicate_overlap_and_out_of_duration(self):
        for value in (
            "nope",
            "2:00-1:00",
            "1-2,1-2",
            "1-3,2-4",
            "0-301",
            "1:60-2:00",
        ):
            with self.subTest(value=value), self.assertRaises(core.TimestampError):
                core.parse_timestamp_ranges(value, 300)

    def test_command_message_detection_ignores_commands_and_preserves_ranges(self):
        self.assertTrue(core.is_command_message(".ytcancel"))
        self.assertTrue(core.is_command_message(".ytcancel now"))
        self.assertTrue(core.is_command_message(".ping"))
        self.assertTrue(core.is_command_message(".help ytdl"))
        self.assertTrue(core.is_command_message("!ytcancel", prefix="!"))
        self.assertTrue(core.is_command_message(".ytcancel", prefix="!"))
        self.assertTrue(core.is_command_message("!ping", prefix="!"))
        self.assertFalse(core.is_command_message(""))
        self.assertFalse(core.is_command_message(None))
        self.assertFalse(core.is_command_message("   "))
        self.assertFalse(core.is_command_message("nope"))

        for non_command in (
            "1:20-2:10",
            "90-2:00",
            "1:00-2:00, 3:00-",
            "first 60s",
            "last 30s",
            "full",
            "full video",
        ):
            with self.subTest(non_command=non_command):
                self.assertFalse(core.is_command_message(non_command, prefix="."))
                ranges = core.parse_timestamp_ranges(non_command, 300)
                self.assertIsInstance(ranges, list)


class StateTests(unittest.TestCase):
    def test_state_is_owner_chat_message_bound_and_expires(self):
        now = [10.0]
        store = core.RequestStore(ttl=5, max_entries=2, clock=lambda: now[0])
        state = store.create(
            owner_id=1,
            chat_id=2,
            command_message_id=3,
            status_message_id=4,
            url="https://example.com",
        )
        self.assertLessEqual(len(state.token), 12)
        self.assertLessEqual(len(f"ytdl:q:{state.token}:audio-m4a".encode()), 64)
        self.assertIs(
            store.get_bound(
                state.token, owner_id=1, chat_id=2, status_message_id=4
            ),
            state,
        )
        for binding in ((9, 2, 4), (1, 9, 4), (1, 2, 9)):
            self.assertIsNone(
                store.get_bound(
                    state.token,
                    owner_id=binding[0],
                    chat_id=binding[1],
                    status_message_id=binding[2],
                )
            )
        now[0] = 15.0
        self.assertEqual(store.cleanup(), (state.token,))
        self.assertTrue(state.cancel_event.is_set())

    def test_replacement_and_bound_evict_cancel_old_state(self):
        store = core.RequestStore(ttl=50, max_entries=1)
        first = store.create(
            owner_id=1, chat_id=2, command_message_id=3,
            status_message_id=4, url="https://example.com/1"
        )
        second = store.create(
            owner_id=1, chat_id=3, command_message_id=5,
            status_message_id=6, url="https://example.com/2"
        )
        self.assertTrue(first.cancel_event.is_set())
        self.assertEqual(len(store), 1)
        self.assertIs(store.find(owner_id=1, chat_id=3), second)


class ServiceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_uses_single_item_safe_options_and_finds_output(self):
        observed = []

        async def immediate(function):
            return function()

        class FakeYDL:
            def __init__(self, options):
                self.options = options
                observed.append(options)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def extract_info(self, _url, download=False):
                if download:
                    path = Path(self.options["outtmpl"].replace("%(id).80s", "abc").replace("%(ext)s", "mp4"))
                    path.write_bytes(b"media")
                    return {"id": "abc", "ext": "mp4"}
                return {"id": "abc", "title": "Example"}

            def prepare_filename(self, _info):
                return self.options["outtmpl"].replace("%(id).80s", "abc").replace("%(ext)s", "mp4")

        service = core.YTDLPService(ydl_factory=FakeYDL)
        service_module = sys.modules[core.YTDLPService.__module__]
        original_to_thread = service_module.asyncio.to_thread
        service_module.asyncio.to_thread = immediate
        try:
            metadata = await service.extract("https://example.com/video")
            self.assertEqual(metadata["id"], "abc")
            with tempfile.TemporaryDirectory() as directory:
                choice = core.build_format_choices({"formats": []})[0]
                output = await service.download(
                    "https://example.com/video", choice, Path(directory)
                )
                self.assertEqual(output.read_bytes(), b"media")
        finally:
            service_module.asyncio.to_thread = original_to_thread
        self.assertTrue(all(item["noplaylist"] for item in observed))
        self.assertTrue(observed[0]["skip_download"])
        self.assertEqual(observed[1]["merge_output_format"], "mp4")
        forbidden = ("cookiefile", "username", "password")
        self.assertTrue(all(key not in observed[1] for key in forbidden))


class WorkspaceCleanupTests(unittest.TestCase):
    def test_private_workspace_cleans_on_failure(self):
        paths = ROOT / "pyUltroid" / "security" / "paths.py"
        spec = importlib.util.spec_from_file_location("ytdl_test_paths", paths)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as root:
            created = None
            with self.assertRaises(RuntimeError):
                with module.private_workspace(root, "ytdl-test-") as workspace:
                    created = workspace
                    (workspace / "partial.part").write_bytes(b"x")
                    raise RuntimeError("stop")
            self.assertIsNotNone(created)
            self.assertFalse(created.exists())


if __name__ == "__main__":
    unittest.main()
