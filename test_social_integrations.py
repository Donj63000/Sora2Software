import http.client
import json
import os
import tempfile
import threading
import types
import unittest
from unittest import mock

import sora2_video
from social_integrations import (
    SOCIAL_DEFAULT_SIZE,
    FacebookAPI,
    TikTokAPI,
    _OAuthCallbackServer,
    is_social_size,
    normalize_social_posts,
)
from sora2_video import (
    FACEBOOK_APP_SECRET_KEYRING_NAME,
    TIKTOK_CLIENT_SECRET_KEYRING_NAME,
    build_history_detail_items,
    build_prompt_preview,
    choose_layout_mode,
    compute_initial_window_geometry,
    load_env,
    normalize_history_record,
)


class FakeVar:
    def __init__(self, value: object = "") -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class FakeButton:
    def __init__(self) -> None:
        self.disabled = False

    def state(self, commands: list[str]) -> None:
        if "disabled" in commands:
            self.disabled = True
        if "!disabled" in commands:
            self.disabled = False


def make_social_app_stub(workdir: str) -> types.SimpleNamespace:
    app = types.SimpleNamespace()
    app.social_accounts = {"tiktok": {}, "facebook": {}}
    app.social_accounts_file = os.path.join(workdir, "social_accounts.json")
    app.facebook_page_tokens = {}
    app.tiktok_client_key_var = FakeVar("")
    app.tiktok_client_secret_var = FakeVar("")
    app.tiktok_redirect_port_var = FakeVar("8765")
    app.facebook_app_id_var = FakeVar("")
    app.facebook_app_secret_var = FakeVar("")
    app.facebook_graph_version_var = FakeVar(sora2_video.DEFAULT_FACEBOOK_GRAPH_VERSION)
    app.facebook_redirect_port_var = FakeVar("8766")
    app.logged_messages: list[tuple[str, str]] = []

    def append_log(message: str, level: str = "info") -> None:
        app.logged_messages.append((level, message))

    app._append_log = append_log
    for method_name in (
        "_normalize_port_value",
        "_ensure_social_settings_shape",
        "_load_social_app_secret_value",
        "_save_social_app_secret_value",
        "_migrate_legacy_social_settings_secrets",
        "_social_accounts_storage_payload",
        "_get_tiktok_settings",
        "_get_facebook_settings",
        "_sync_social_settings_vars",
        "_format_tiktok_callback_url",
        "_format_facebook_callback_url",
        "_build_tiktok_connect_hint_text",
        "_build_tiktok_guided_config_message",
        "_build_tiktok_connect_error_message",
        "_build_social_help_text",
        "_save_social_accounts",
        "_load_social_accounts",
        "_build_tiktok_api",
        "_build_facebook_api",
    ):
        setattr(
            app,
            method_name,
            types.MethodType(getattr(sora2_video.SoraVideoApp, method_name), app),
        )
    return app


def make_history_actions_stub() -> types.SimpleNamespace:
    app = types.SimpleNamespace()
    app.history_open_btn = FakeButton()
    app.history_export_btn = FakeButton()
    app.history_reuse_btn = FakeButton()
    app.history_delete_btn = FakeButton()
    app._set_history_actions_state = types.MethodType(
        getattr(sora2_video.SoraVideoApp, "_set_history_actions_state"),
        app,
    )
    return app


class SocialIntegrationTests(unittest.TestCase):
    def _exercise_callback_request(self, request_path: str) -> None:
        server = _OAuthCallbackServer(("127.0.0.1", 0), "/tiktok/callback")
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            connection.request("GET", f"{request_path}?code=demo-code&state=demo-state")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("Connexion terminee", body)
            self.assertTrue(server.event.wait(1))
            self.assertEqual(server.payload["code"], "demo-code")
            self.assertEqual(server.payload["state"], "demo-state")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_build_prompt_preview_uses_fallback_and_truncates(self) -> None:
        self.assertEqual(build_prompt_preview("", fallback="Paris de nuit"), "Paris de nuit")
        preview = build_prompt_preview(" ".join(["plan"] * 40), max_length=24)
        self.assertTrue(preview.endswith("…"))
        self.assertLessEqual(len(preview), 24)

    def test_is_social_size_accepts_supported_sizes(self) -> None:
        self.assertTrue(is_social_size("720x1280"))
        self.assertTrue(is_social_size(SOCIAL_DEFAULT_SIZE))
        self.assertFalse(is_social_size("1280x720"))

    def test_normalize_history_record_backfills_prompt_preview_for_legacy_rows(self) -> None:
        record = normalize_history_record(
            {
                "name": "demo.mp4",
                "path": "videos/demo.mp4",
                "resolution": "1280x720",
            },
            "C:/workspace/app",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["prompt"], "")
        self.assertEqual(record["prompt_preview"], "demo.mp4")
        self.assertEqual(record["path"], "C:\\workspace\\app\\videos\\demo.mp4")

    def test_normalize_history_record_rejects_missing_path(self) -> None:
        self.assertIsNone(normalize_history_record({"name": "x"}, "C:/workspace/app"))

    def test_normalize_history_record_keeps_prompt_and_social_flag(self) -> None:
        record = normalize_history_record(
            {
                "name": "reel.mp4",
                "path": "C:/videos/reel.mp4",
                "prompt": "Plan cinéma sur une rue pluvieuse avec travelling avant.",
                "resolution": "720x1280",
                "social_posts": [{"platform": "TikTok", "status": "Publie"}],
            },
            "C:/workspace/app",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(
            record["prompt_preview"],
            "Plan cinéma sur une rue pluvieuse avec travelling avant.",
        )
        self.assertTrue(record["social_ready"])
        self.assertEqual(len(record["social_posts"]), 1)

    def test_normalize_history_record_uses_legacy_size_for_social_ready(self) -> None:
        record = normalize_history_record(
            {
                "name": "legacy.mp4",
                "path": "videos/legacy.mp4",
                "size": "720x1280",
            },
            "C:/workspace/app",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["resolution"], "720x1280")
        self.assertTrue(record["social_ready"])

    def test_normalize_social_posts_filters_invalid_rows(self) -> None:
        rows = normalize_social_posts(
            [
                {
                    "platform": "TikTok",
                    "target_id": "abc",
                    "target_name": "Compte",
                    "caption": "Hello",
                    "published_at": "2026-03-07T10:00:00",
                    "status": "Publie",
                    "remote_id": "pub-1",
                    "error": "",
                },
                "ignored",
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform"], "TikTok")
        self.assertEqual(rows[0]["remote_id"], "pub-1")

    def test_normalize_social_posts_backfills_publish_id(self) -> None:
        rows = normalize_social_posts(
            [{"platform": "Facebook", "publish_id": "x-1", "status": "Publie"}]
        )
        self.assertEqual(rows[0]["publish_id"], "x-1")
        self.assertEqual(rows[0]["remote_id"], "x-1")

    def test_tiktok_redirect_uri_uses_loopback_http_callback(self) -> None:
        api = TikTokAPI(client_key="demo-key", redirect_port=9911)
        self.assertEqual(api.redirect_uri, "http://127.0.0.1:9911/tiktok/callback")

    def test_oauth_callback_accepts_path_with_or_without_trailing_slash(self) -> None:
        for request_path in ("/tiktok/callback", "/tiktok/callback/"):
            with self.subTest(request_path=request_path):
                self._exercise_callback_request(request_path)

    def test_tiktok_help_and_guidance_call_out_desktop_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = make_social_app_stub(temp_dir)
            help_text = app._build_social_help_text()
            config_message = app._build_tiktok_guided_config_message("le Client key TikTok")

        self.assertIn("Desktop Login Kit", help_text)
        self.assertIn("http://127.0.0.1:8765/tiktok/callback", help_text)
        self.assertIn("target user Sandbox", help_text)
        self.assertIn("Desktop Login Kit", config_message)
        self.assertIn("http://127.0.0.1:8765/tiktok/callback", config_message)
        self.assertIn("https://", config_message)

    def test_tiktok_timeout_error_gets_desktop_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = make_social_app_stub(temp_dir)
            message = app._build_tiktok_connect_error_message(
                "Connexion annulee ou expiree avant retour OAuth."
            )

        self.assertIn("Desktop Login Kit", message)
        self.assertIn("http://127.0.0.1:8765/tiktok/callback", message)
        self.assertIn("Sandbox", message)

    def test_load_env_overrides_managed_app_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = os.path.join(temp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as handle:
                handle.write("OPENAI_API_KEY=file-value\n")
                handle.write("CUSTOM_KEY=file-custom\n")
            with mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "stale-value", "CUSTOM_KEY": "process-value"},
                clear=True,
            ):
                load_env(env_path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "file-value")
                self.assertEqual(os.environ["CUSTOM_KEY"], "process-value")

    def test_load_social_accounts_recovers_with_env_values_on_failures(self) -> None:
        env_content = "\n".join(
            [
                "TIKTOK_CLIENT_KEY=env-tiktok-key",
                "TIKTOK_CLIENT_SECRET=env-tiktok-secret",
                "TIKTOK_REDIRECT_PORT=9101",
                "FACEBOOK_APP_ID=env-facebook-id",
                "FACEBOOK_APP_SECRET=env-facebook-secret",
                "FACEBOOK_GRAPH_VERSION=v42.0",
                "FACEBOOK_REDIRECT_PORT=9102",
            ]
        )
        scenarios = {
            "missing": None,
            "invalid_json": "{",
            "non_dict": "[]",
        }
        for label, raw_payload in scenarios.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temp_dir:
                    env_path = os.path.join(temp_dir, ".env")
                    with open(env_path, "w", encoding="utf-8") as handle:
                        handle.write(env_content)
                    social_path = os.path.join(temp_dir, "social_accounts.json")
                    if raw_payload is not None:
                        with open(social_path, "w", encoding="utf-8") as handle:
                            handle.write(raw_payload)
                    app = make_social_app_stub(temp_dir)
                    with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                        sora2_video,
                        "ENV_PATH",
                        env_path,
                    ), mock.patch("sora2_video.load_secret_json", return_value={}):
                        app._load_social_accounts()
                    self.assertEqual(app.social_accounts, {"tiktok": {}, "facebook": {}})
                    self.assertEqual(app.tiktok_client_key_var.get(), "env-tiktok-key")
                    self.assertEqual(app.tiktok_client_secret_var.get(), "env-tiktok-secret")
                    self.assertEqual(app.tiktok_redirect_port_var.get(), "9101")
                    self.assertEqual(app.facebook_app_id_var.get(), "env-facebook-id")
                    self.assertEqual(app.facebook_app_secret_var.get(), "env-facebook-secret")
                    self.assertEqual(app.facebook_graph_version_var.get(), "v42.0")
                    self.assertEqual(app.facebook_redirect_port_var.get(), "9102")
                    if label == "missing":
                        self.assertEqual(app.logged_messages, [])
                    else:
                        self.assertTrue(app.logged_messages)

    def test_social_accounts_migration_moves_app_secrets_to_keyring(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            social_path = os.path.join(temp_dir, "social_accounts.json")
            with open(social_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "tiktok": {
                            "connected": True,
                            "display_name": "TikTok",
                            "settings": {
                                "client_key": "tk-key",
                                "client_secret": "tk-secret",
                                "redirect_port": "9201",
                            },
                        },
                        "facebook": {
                            "connected": True,
                            "user_name": "Meta",
                            "settings": {
                                "app_id": "fb-id",
                                "app_secret": "fb-secret",
                                "graph_version": "v43.0",
                                "redirect_port": "9202",
                            },
                        },
                    },
                    handle,
                    indent=2,
                )
            secret_store: dict[str, dict[str, str]] = {}

            def fake_load_secret_json(secret_name: str) -> dict[str, str]:
                return dict(secret_store.get(secret_name, {}))

            def fake_save_secret_json(secret_name: str, payload: dict[str, str]) -> None:
                secret_store[secret_name] = dict(payload)

            app = make_social_app_stub(temp_dir)
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                sora2_video,
                "ENV_PATH",
                os.path.join(temp_dir, ".env"),
            ), mock.patch(
                "sora2_video.load_secret_json",
                side_effect=fake_load_secret_json,
            ), mock.patch(
                "sora2_video.save_secret_json",
                side_effect=fake_save_secret_json,
            ):
                app._load_social_accounts()
                tiktok_api = app._build_tiktok_api()
                facebook_api = app._build_facebook_api()

            with open(social_path, "r", encoding="utf-8") as handle:
                cleaned_payload = json.load(handle)

            self.assertNotIn("client_secret", cleaned_payload["tiktok"]["settings"])
            self.assertNotIn("app_secret", cleaned_payload["facebook"]["settings"])
            self.assertEqual(
                secret_store[TIKTOK_CLIENT_SECRET_KEYRING_NAME]["client_secret"],
                "tk-secret",
            )
            self.assertEqual(
                secret_store[FACEBOOK_APP_SECRET_KEYRING_NAME]["app_secret"],
                "fb-secret",
            )
            self.assertIsInstance(tiktok_api, TikTokAPI)
            self.assertEqual(tiktok_api.client_secret, "tk-secret")
            self.assertIsInstance(facebook_api, FacebookAPI)
            self.assertEqual(facebook_api.app_secret, "fb-secret")


class FrontendSupportTests(unittest.TestCase):
    def test_choose_layout_mode_switches_to_compact_below_threshold(self) -> None:
        self.assertEqual(choose_layout_mode(1439, 900), "compact")
        self.assertEqual(choose_layout_mode(1600, 819), "compact")
        self.assertEqual(choose_layout_mode(1440, 820), "regular")

    def test_compute_initial_window_geometry_is_centered_for_1366x768(self) -> None:
        geometry = compute_initial_window_geometry(1366, 768)
        self.assertEqual(geometry, (1326, 720, 20, 24))

    def test_build_history_detail_items_formats_library_grid_values(self) -> None:
        values = build_history_detail_items(
            {
                "model": "sora-2",
                "duration_seconds": 12,
                "resolution": "1280x720",
                "social_posts": [{"id": "1"}, {"id": "2"}],
                "path": "C:/videos/demo.mp4",
            },
            file_exists=False,
            formatted_date="08/03/2026 01:20",
            formatted_size="8.2 MB",
            social_ready=True,
        )

        self.assertEqual(values["modele"], "sora-2")
        self.assertEqual(values["duree"], "12s")
        self.assertEqual(values["format"], "1280x720")
        self.assertEqual(values["taille"], "8.2 MB")
        self.assertEqual(values["reseaux"], "Prêt")
        self.assertEqual(values["publications"], "2")
        self.assertEqual(values["date"], "08/03/2026 01:20")
        self.assertEqual(values["etat"], "Fichier introuvable")
        self.assertEqual(values["chemin"], "C:/videos/demo.mp4")

    def test_history_actions_state_keeps_reuse_and_delete_when_file_missing(self) -> None:
        app = make_history_actions_stub()

        app._set_history_actions_state(has_selection=True, file_exists=False)

        self.assertTrue(app.history_open_btn.disabled)
        self.assertTrue(app.history_export_btn.disabled)
        self.assertFalse(app.history_reuse_btn.disabled)
        self.assertFalse(app.history_delete_btn.disabled)

    def test_history_actions_state_enables_open_and_export_when_file_exists(self) -> None:
        app = make_history_actions_stub()

        app._set_history_actions_state(has_selection=True, file_exists=True)

        self.assertFalse(app.history_open_btn.disabled)
        self.assertFalse(app.history_export_btn.disabled)
        self.assertFalse(app.history_reuse_btn.disabled)
        self.assertFalse(app.history_delete_btn.disabled)


if __name__ == "__main__":
    unittest.main()
