"""draft:answer-gui のテストスイート（stdlib unittest）。

Run: cd scripts/ && python3 -m unittest test_answer_gui -v
"""
from __future__ import annotations

import json
import os
import shutil
import time
import unittest
import unittest.mock
import urllib.request

import answer_gui as ag


# ── normalize_input ──────────────────────────────────────────────────────

class NormalizeInputTests(unittest.TestCase):
    def test_list_form(self):
        raw = [{"id": "q1", "title": "T"}]
        mode, payload, kind = ag.normalize_input(raw)
        self.assertIsNone(mode)
        self.assertEqual(payload, raw)
        self.assertEqual(kind, "items")

    def test_object_with_items(self):
        raw = {"mode": "wizard", "items": [{"id": "q1", "title": "T"}]}
        mode, payload, kind = ag.normalize_input(raw)
        self.assertEqual(mode, "wizard")
        self.assertEqual(payload, raw["items"])
        self.assertEqual(kind, "items")

    def test_object_with_rows(self):
        raw = {"mode": "diff-table", "rows": [
            {"id": "r1", "label": "L", "current": "C", "proposed": "P"}
        ]}
        mode, payload, kind = ag.normalize_input(raw)
        self.assertEqual(mode, "diff-table")
        self.assertEqual(payload, raw["rows"])
        self.assertEqual(kind, "rows")

    def test_rejects_dict_without_items_or_rows(self):
        with self.assertRaisesRegex(ValueError, "items.*rows"):
            ag.normalize_input({"mode": "card"})

    def test_rejects_string(self):
        with self.assertRaises(ValueError):
            ag.normalize_input("not a list or dict")


# ── validate ─────────────────────────────────────────────────────────────

class ValidateTests(unittest.TestCase):
    def test_items_requires_id_and_title(self):
        ok, err = ag.validate([{"id": "q1"}], "items")
        self.assertFalse(ok)
        self.assertIn("title", err)

    def test_items_ok(self):
        ok, err = ag.validate(
            [{"id": "q1", "title": "T", "options": ["A", "B"]}], "items"
        )
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_rows_requires_4_keys(self):
        ok, err = ag.validate(
            [{"id": "r1", "label": "L", "current": "C"}], "rows"
        )
        self.assertFalse(ok)
        self.assertIn("proposed", err)

    def test_rejects_empty(self):
        ok, err = ag.validate([], "items")
        self.assertFalse(ok)


# ── auto_layout ──────────────────────────────────────────────────────────

class AutoLayoutTests(unittest.TestCase):
    def test_fewer_than_4_items_is_card(self):
        items = [{"id": f"q{i}", "title": "T", "options": ["A"]} for i in range(3)]
        self.assertEqual(ag.auto_layout(items), "card")

    def test_4_items_with_options_is_table(self):
        items = [{"id": f"q{i}", "title": "T", "options": ["A"]} for i in range(4)]
        self.assertEqual(ag.auto_layout(items), "table")

    def test_4_items_mostly_free_text_is_card(self):
        items = [{"id": f"q{i}", "title": "T"} for i in range(4)]
        self.assertEqual(ag.auto_layout(items), "card")


# ── pick_port ────────────────────────────────────────────────────────────

class PickPortTests(unittest.TestCase):
    def test_returns_int_in_valid_range(self):
        port = ag.pick_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 1024)
        self.assertLess(port, 65536)


# ── find_browser_command ─────────────────────────────────────────────────

class FindBrowserCommandTests(unittest.TestCase):
    def test_returns_none_when_no_match(self):
        with unittest.mock.patch.object(ag.shutil, "which", return_value=None), \
             unittest.mock.patch.object(ag.os.path, "exists", return_value=False):
            self.assertIsNone(ag.find_browser_command(["nonexistent-browser"]))

    def test_returns_absolute_path_if_exists(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as tmp:
            self.assertEqual(ag.find_browser_command([tmp.name]), tmp.name)

    def test_falls_back_to_shutil_which(self):
        def fake_which(name):
            return f"/usr/bin/{name}" if name == "google-chrome" else None
        with unittest.mock.patch.object(ag.os.path, "exists", return_value=False), \
             unittest.mock.patch.object(ag.shutil, "which", side_effect=fake_which):
            self.assertEqual(
                ag.find_browser_command(["google-chrome", "msedge"]),
                "/usr/bin/google-chrome",
            )


# ── render_html / render_card ────────────────────────────────────────────

class RenderHtmlTests(unittest.TestCase):
    def test_contains_doctype_and_meta(self):
        html = ag.render_html(
            payload=[{"id": "q1", "title": "T1"}],
            mode="card",
            kind="items",
            title="test",
        )
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('charset="utf-8"', html)
        self.assertIn("<title>test</title>", html)

    def test_escapes_xss(self):
        html = ag.render_html(
            payload=[{"id": "q1", "title": "<script>alert(1)</script>"}],
            mode="card",
            kind="items",
            title="test",
        )
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


class RenderCardTests(unittest.TestCase):
    def test_includes_title_context_options_memo(self):
        html = ag.render_card({
            "id": "q1",
            "title": "件名X",
            "context": "状況Y",
            "options": ["A: 案A", "B: 案B"],
            "memo_label": "補足Z",
        }, idx=1)
        self.assertIn("件名X", html)
        self.assertIn("状況Y", html)
        self.assertIn("A: 案A", html)
        self.assertIn("B: 案B", html)
        self.assertIn("補足Z", html)
        self.assertIn('name="choice-q1"', html)
        self.assertIn('type="radio"', html)
        self.assertIn('name="memo-q1"', html)

    def test_free_text_when_no_options(self):
        html = ag.render_card({"id": "q1", "title": "T"}, idx=1)
        self.assertNotIn('type="radio"', html)
        self.assertIn('name="memo-q1"', html)


class RenderTableTests(unittest.TestCase):
    def test_has_header_row(self):
        items = [
            {"id": f"q{i}", "title": f"T{i}", "options": ["A", "B"]} for i in range(4)
        ]
        html = ag.render_table(items)
        self.assertIn("<table", html)
        self.assertIn("件名", html)
        self.assertIn("選択肢", html)
        self.assertIn("メモ", html)

    def test_with_group_column(self):
        items = [
            {"id": "q1", "title": "T1", "options": ["A"], "group": "PJ-Alpha"},
            {"id": "q2", "title": "T2", "options": ["A"], "group": "PJ-Alpha"},
            {"id": "q3", "title": "T3", "options": ["A"], "group": "PJ-Beta"},
        ]
        html = ag.render_table(items)
        self.assertIn("PJ-Alpha", html)
        self.assertIn("PJ-Beta", html)
        # PJ ヘッダがあること
        self.assertIn("<th>PJ</th>", html)

    def test_radio_inputs_per_item(self):
        items = [{"id": "q1", "title": "T", "options": ["A", "B"]}]
        html = ag.render_table(items)
        # A と B で 2 つの radio
        self.assertEqual(html.count('name="choice-q1"'), 2)


class RenderYesNoTests(unittest.TestCase):
    def test_centered_with_buttons(self):
        item = {"id": "q1", "title": "やる?", "options": ["はい", "いいえ"]}
        html = ag.render_yes_no(item)
        self.assertIn("やる?", html)
        self.assertIn("はい", html)
        self.assertIn("いいえ", html)
        self.assertIn('name="choice-q1"', html)

    def test_render_html_yesno_uses_first_item(self):
        payload = [{"id": "q1", "title": "TitleX", "options": ["A", "B"]}]
        html = ag.render_html(payload, "yes-no", "items")
        self.assertIn("TitleX", html)
        self.assertIn('name="choice-q1"', html)


class RenderWizardTests(unittest.TestCase):
    def test_renders_all_pages_first_active(self):
        items = [{"id": f"q{i}", "title": f"T{i}"} for i in range(3)]
        html = ag.render_wizard(items)
        # 3 ページ分のセクションが存在
        self.assertEqual(html.count('class="wiz-page"'), 3)
        # 最初のページのみ active="true"
        self.assertEqual(html.count('data-active="true"'), 1)
        self.assertEqual(html.count('data-active="false"'), 2)

    def test_has_stepper_and_nav(self):
        items = [{"id": f"q{i}", "title": f"T{i}"} for i in range(2)]
        html = ag.render_wizard(items)
        self.assertIn("wiz-stepper", html)
        self.assertIn("wiz-next", html)
        self.assertIn("wiz-prev", html)


class RenderDiffTableTests(unittest.TestCase):
    def test_basic(self):
        rows = [
            {"id": "summary", "label": "summary", "current": "old", "proposed": "new"},
            {"id": "due", "label": "due", "current": "", "proposed": "2026-05-20"},
        ]
        html = ag.render_diff_table(rows)
        self.assertIn("summary", html)
        self.assertIn("old", html)
        self.assertIn("new", html)
        self.assertIn("2026-05-20", html)
        # 空の current は「（未設定）」
        self.assertIn("（未設定）", html)
        self.assertIn('type="checkbox"', html)

    def test_changed_row_marked(self):
        rows = [
            {"id": "a", "label": "a", "current": "x", "proposed": "y"},
            {"id": "b", "label": "b", "current": "z", "proposed": "z"},
        ]
        html = ag.render_diff_table(rows)
        self.assertIn('data-changed="true"', html)
        self.assertIn('data-changed="false"', html)


class HttpServerTests(unittest.TestCase):
    def test_get_returns_html(self):
        payload = [{"id": "q1", "title": "TitleAlpha"}]
        server, port, result = ag.start_server(payload, "card", "items", "test-title")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
                body = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 200)
                self.assertIn("<!DOCTYPE html>", body)
                self.assertIn("TitleAlpha", body)
                self.assertIn("test-title", body)
        finally:
            server.shutdown()

    def test_submit_writes_result(self):
        payload = [{"id": "q1", "title": "T", "options": ["A", "B"]}]
        server, port, result = ag.start_server(payload, "card", "items", "t")
        try:
            data = [{"id": "q1", "choice": "A", "memo": "ok"}]
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/submit",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
            time.sleep(0.1)
            self.assertEqual(result["status"], "submitted")
            self.assertEqual(result["data"], data)
        finally:
            server.shutdown()

    def test_cancel(self):
        payload = [{"id": "q1", "title": "T"}]
        server, port, result = ag.start_server(payload, "card", "items", "t")
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/cancel", method="POST", data=b""
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
            time.sleep(0.1)
            self.assertEqual(result["status"], "cancelled")
        finally:
            server.shutdown()

    def test_unknown_path_404(self):
        payload = [{"id": "q1", "title": "T"}]
        server, port, result = ag.start_server(payload, "card", "items", "t")
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/nope")
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()


class OpenWindowTests(unittest.TestCase):
    def test_uses_chromium_app_when_available(self):
        called = {}
        def fake_popen(args, **kw):
            called["args"] = args
            return None
        with unittest.mock.patch.object(ag.subprocess, "Popen", fake_popen), \
             unittest.mock.patch.object(
                 ag, "find_browser_command",
                 side_effect=lambda lst: "/fake/chrome" if lst is ag.CHROMIUM_LIKE else None,
             ):
            kind = ag.open_window("http://127.0.0.1:12345/")
        self.assertEqual(kind, "chromium-app")
        self.assertIn("--app=http://127.0.0.1:12345/", called["args"])
        self.assertEqual(called["args"][0], "/fake/chrome")

    def test_falls_back_to_firefox(self):
        called = {}
        def fake_popen(args, **kw):
            called["args"] = args
        with unittest.mock.patch.object(ag.subprocess, "Popen", fake_popen), \
             unittest.mock.patch.object(
                 ag, "find_browser_command",
                 side_effect=lambda lst: "/fake/firefox" if lst is ag.FIREFOX_LIKE else None,
             ):
            kind = ag.open_window("http://127.0.0.1:12345/")
        self.assertEqual(kind, "firefox")
        self.assertIn("-new-window", called["args"])
        self.assertEqual(called["args"][0], "/fake/firefox")

    def test_falls_back_to_webbrowser(self):
        called = {}
        with unittest.mock.patch.object(ag, "find_browser_command", return_value=None), \
             unittest.mock.patch.object(
                 ag.webbrowser, "open_new",
                 side_effect=lambda url: called.setdefault("url", url),
             ):
            kind = ag.open_window("http://127.0.0.1:12345/")
        self.assertEqual(kind, "fallback")
        self.assertEqual(called["url"], "http://127.0.0.1:12345/")


class MarkdownInlineTests(unittest.TestCase):
    def test_plain_text_wrapped_in_p(self):
        self.assertEqual(ag.render_markdown("hello"), "<p>hello</p>")

    def test_bold(self):
        self.assertIn("<strong>bold</strong>", ag.render_markdown("**bold**"))

    def test_code(self):
        self.assertIn("<code>x</code>", ag.render_markdown("`x`"))

    def test_link(self):
        out = ag.render_markdown("[click](https://example.com)")
        self.assertIn('href="https://example.com"', out)
        self.assertIn('target="_blank"', out)
        self.assertIn('rel="noopener"', out)
        self.assertIn(">click</a>", out)

    def test_escape_xss(self):
        out = ag.render_markdown("<script>alert(1)</script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_paragraph_separation(self):
        out = ag.render_markdown("first\n\nsecond")
        self.assertIn("<p>first</p>", out)
        self.assertIn("<p>second</p>", out)


class MarkdownBlockTests(unittest.TestCase):
    def test_bullet_list(self):
        out = ag.render_markdown("- one\n- two\n- three")
        self.assertIn("<ul>", out)
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn("<li>one</li>", out)

    def test_bullet_with_bold(self):
        out = ag.render_markdown("- **A**: hello\n- B: world")
        self.assertIn("<strong>A</strong>", out)

    def test_blockquote(self):
        out = ag.render_markdown("> warning\n> note")
        self.assertIn("<blockquote>", out)
        self.assertIn("warning", out)

    def test_mixed_paragraph_and_list(self):
        out = ag.render_markdown("intro paragraph\n\n- item 1\n- item 2")
        self.assertIn("<p>intro paragraph</p>", out)
        self.assertIn("<ul>", out)

    def test_mixed_paragraph_and_list_no_blank_line(self):
        """空行なしで prefix paragraph + bullets が連続するケース (v2.1 bugfix)。"""
        out = ag.render_markdown(
            "デビュー戦観察ベースで 5 候補:\n- **A**: alpha\n- **B**: beta"
        )
        self.assertIn("<p>デビュー戦観察ベースで 5 候補:</p>", out)
        self.assertIn("<ul>", out)
        self.assertEqual(out.count("<li>"), 2)
        self.assertIn("<strong>A</strong>", out)
        # bullets が <p> の中に紛れ込んでいないこと
        self.assertNotIn("- <strong>A</strong>", out)


class MarkdownChipTests(unittest.TestCase):
    def test_kagi_quote_becomes_chip(self):
        out = ag.render_markdown("「想定読み手」が浮く")
        self.assertIn('<span class="chip">想定読み手</span>', out)

    def test_multiple_chips(self):
        out = ag.render_markdown("「A」と「B」を比較")
        self.assertEqual(out.count('class="chip"'), 2)

    def test_chip_with_inner_bold(self):
        out = ag.render_markdown("「**重要**な点」")
        self.assertIn('class="chip"', out)
        self.assertIn("<strong>重要</strong>", out)

    def test_white_square_bracket_becomes_info_chip(self):
        """『』 → chip-info（青系）"""
        out = ag.render_markdown("『トピック A』を検討")
        self.assertIn('<span class="chip chip-info">トピック A</span>', out)

    def test_kuro_kakko_becomes_good_chip(self):
        """【】 → chip-good（緑系）"""
        out = ag.render_markdown("【推奨】の方針")
        self.assertIn('<span class="chip chip-good">推奨</span>', out)

    def test_three_chip_variants_coexist(self):
        out = ag.render_markdown("「default」と『info』と【good】")
        self.assertIn('class="chip">default', out)
        self.assertIn('class="chip chip-info">info', out)
        self.assertIn('class="chip chip-good">good', out)


class CollapseTests(unittest.TestCase):
    def test_short_text_no_collapse(self):
        collapse, head, tail = ag.should_collapse("short")
        self.assertFalse(collapse)
        self.assertEqual(head, "short")
        self.assertEqual(tail, "")

    def test_long_unstructured_collapses(self):
        long_text = "あ" * 250 + "\n\n" + "い" * 100 + "\n\n" + "う" * 100
        collapse, head, tail = ag.should_collapse(long_text)
        self.assertTrue(collapse)
        self.assertTrue(head.startswith("あ"))
        self.assertNotEqual(tail, "")

    def test_bullet_list_never_collapses(self):
        text = "intro\n\n- " + ("a" * 100) + "\n- " + ("b" * 100) + "\n- " + ("c" * 100)
        collapse, head, tail = ag.should_collapse(text)
        self.assertFalse(collapse)

    def test_tldr_prefix_always_collapses(self):
        text = "TL;DR: short summary\n\nmore details here..."
        collapse, head, tail = ag.should_collapse(text)
        self.assertTrue(collapse)
        self.assertIn("TL;DR:", head)
        self.assertIn("more details", tail)


class OptionNormalizationTests(unittest.TestCase):
    def test_string_option(self):
        result = ag.normalize_option("A: scripts/")
        self.assertEqual(result["value"], "A: scripts/")
        self.assertFalse(result.get("recommended"))
        self.assertEqual(result.get("tone", "neutral"), "neutral")

    def test_object_option_full(self):
        opt = {"value": "B", "recommended": True, "tone": "add", "effect": "効果"}
        result = ag.normalize_option(opt)
        self.assertEqual(result["value"], "B")
        self.assertTrue(result["recommended"])
        self.assertEqual(result["tone"], "add")
        self.assertEqual(result["effect"], "効果")


class RenderOptionTests(unittest.TestCase):
    def test_string_option_renders_radio(self):
        out = ag.render_option("A: 案", "q1", "choice-q1")
        self.assertIn('type="radio"', out)
        self.assertIn('name="choice-q1"', out)
        self.assertIn('value="A: 案"', out)
        self.assertIn("A: 案", out)

    def test_recommended_shows_star(self):
        opt = {"value": "X", "recommended": True}
        out = ag.render_option(opt, "q1", "choice-q1")
        self.assertIn("★", out)
        self.assertIn("recommended", out)  # CSS class

    def test_tone_class(self):
        for tone in ("add", "replace", "remove", "minimum", "neutral"):
            opt = {"value": "v", "tone": tone}
            out = ag.render_option(opt, "q1", "choice-q1")
            self.assertIn(f"tone-{tone}", out)

    def test_effect_renders_as_subtext(self):
        opt = {"value": "v", "effect": "1 行説明"}
        out = ag.render_option(opt, "q1", "choice-q1")
        self.assertIn("1 行説明", out)
        self.assertIn('class="effect"', out)


class RenderCardV2Tests(unittest.TestCase):
    def test_context_renders_markdown(self):
        item = {"id": "q1", "title": "T", "context": "**bold** in ctx"}
        html = ag.render_card(item, 1)
        self.assertIn("<strong>bold</strong>", html)

    def test_long_context_collapses(self):
        long_ctx = "あ" * 300 + "\n\n" + "い" * 100
        item = {"id": "q1", "title": "T", "context": long_ctx}
        html = ag.render_card(item, 1)
        self.assertIn("<details", html)
        self.assertIn("<summary", html)

    def test_object_options_render(self):
        item = {
            "id": "q1", "title": "T",
            "options": [
                {"value": "A: 案", "recommended": True, "tone": "add", "effect": "良い"},
                "B: plain",
            ],
        }
        html = ag.render_card(item, 1)
        self.assertIn("★", html)
        self.assertIn("tone-add", html)
        self.assertIn("良い", html)
        self.assertIn("B: plain", html)  # 文字列形式も健在

    def test_kagi_chip_in_context(self):
        item = {"id": "q1", "title": "T", "context": "「想定読み手」が浮く"}
        html = ag.render_card(item, 1)
        self.assertIn('class="chip">想定読み手</span>', html)


class RenderTableV2Tests(unittest.TestCase):
    def test_table_context_renders_markdown(self):
        items = [{"id": "q1", "title": "T", "context": "**bold** in ctx", "options": ["A"]}]
        html = ag.render_table(items)
        self.assertIn("<strong>bold</strong>", html)

    def test_table_object_options(self):
        items = [{
            "id": "q1", "title": "T",
            "options": [{"value": "X", "recommended": True, "tone": "add"}],
        }]
        html = ag.render_table(items)
        self.assertIn("★", html)
        self.assertIn("tone-add", html)


class RenderYesNoV2Tests(unittest.TestCase):
    def test_yesno_context_renders_markdown(self):
        item = {"id": "q1", "title": "T", "context": "「重要」な判断", "options": ["はい", "いいえ"]}
        html = ag.render_yes_no(item)
        self.assertIn('class="chip">重要', html)

    def test_yesno_object_options(self):
        item = {
            "id": "q1", "title": "T",
            "options": [{"value": "GO", "recommended": True}, "NO-GO"],
        }
        html = ag.render_yes_no(item)
        self.assertIn("★", html)


if __name__ == "__main__":
    unittest.main()
