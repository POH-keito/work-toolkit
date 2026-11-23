#!/usr/bin/env python3
"""draft:answer-gui — 確認質問への HTML/ブラウザ回答ツール（依存ゼロ・Python stdlib のみ）。

Usage:
    python3 answer_gui.py [--layout <mode>] <input.json> <output.json>

入力 JSON（配列 or object）:
    # 配列形式（従来互換）
    [{"id":"q1","title":"...","context":"...","options":["A:..."],"memo_label":"補足"}]
    # object + mode 形式
    {"mode":"wizard","items":[...]}
    {"mode":"diff-table","title":"...","rows":[{id,label,current,proposed}]}

出力 JSON:
    [{"id":"q1","choice":"A:...","memo":""}]               # card/table/yes-no/wizard
    [{"id":"q1","approved":true,"value":"...","memo":""}]  # diff-table

Exit codes: 0=Submit, 1=Cancel/Timeout, 2=error

レイアウト（優先順位: --layout > input の mode > kind=rows なら diff-table > 自動判定）:
  card / table / yes-no / wizard / diff-table
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

IMPLEMENTED_MODES = {"card", "table", "yes-no", "wizard", "diff-table"}


# ─── CSS / Design tokens（HTML/CSS 用 SSOT） ──────────────────────────────

CSS = """
:root {
  --font-stack: system-ui, -apple-system, BlinkMacSystemFont,
                "Hiragino Sans", "Yu Gothic UI", "Segoe UI Variable", "Segoe UI",
                "Helvetica Neue", sans-serif;
  --bg: #ffffff;
  --surface: #fafafa;
  --border: #e5e7eb;
  --text: #1a1a1a;
  --text-muted: #6b7280;
  --accent: #2563eb;
  --accent-hover: #1d4ed8;
  --danger: #dc2626;
  --success: #16a34a;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  font-family: var(--font-stack);
  font-size: 15px;
  color: var(--text);
  background: var(--bg);
  line-height: 1.55;
}
.container { max-width: 920px; margin: 0 auto; padding: 24px 20px 96px; }
body[data-mode="table"] .container,
body[data-mode="diff-table"] .container { max-width: 1280px; }
h1.page-title { font-size: 22px; margin: 0 0 18px; font-weight: 600; }

/* Card */
.card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 14px;
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.card.invalid { border-color: var(--danger); box-shadow: 0 0 0 3px rgba(220,38,38,0.12); }
.card h2 { font-size: 16px; margin: 0 0 8px; font-weight: 600; }
.card .ctx { color: var(--text-muted); margin: 6px 0 12px; }
.card label.opt {
  display: block; padding: 8px 10px; margin: 4px 0;
  border: 1px solid var(--border); border-radius: 8px;
  cursor: pointer; transition: all 0.12s; background: #fff;
}
.card label.opt:hover { background: #eff6ff; border-color: #93c5fd; }
.card label.opt:has(input:checked) {
  background: #eff6ff; border-color: var(--accent);
  color: var(--accent); font-weight: 600;
}
.card .memo-wrap { margin-top: 12px; }
.card .memo-label { font-size: 13px; color: var(--text-muted); margin-bottom: 4px; }
.card textarea {
  width: 100%; min-height: 64px; padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  font-family: var(--font-stack); font-size: 14px;
  resize: vertical;
}
.card textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; border-color: transparent; }

/* Footer */
.footer {
  position: fixed; left: 0; right: 0; bottom: 0;
  background: rgba(255,255,255,0.96);
  border-top: 1px solid var(--border);
  padding: 12px 24px;
  display: flex; align-items: center; gap: 12px;
  backdrop-filter: blur(8px);
}
.footer .status { color: var(--text-muted); font-size: 13px; flex: 1; }
.footer .status.ok { color: var(--success); font-weight: 600; }
.footer .status.error { color: var(--danger); font-weight: 600; }
button {
  padding: 8px 18px; border-radius: 8px; font-family: var(--font-stack);
  font-size: 14px; cursor: pointer; border: 1px solid var(--border);
  background: white; color: var(--text);
}
button.primary {
  background: var(--accent); color: white; border-color: var(--accent);
  font-weight: 600;
}
button.primary:hover { background: var(--accent-hover); }
button:hover { background: #f8fafc; }

/* Table mode */
.answer-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.answer-table th {
  background: #1e293b; color: white; padding: 10px;
  text-align: left; font-weight: 600; letter-spacing: 0.4px;
}
.answer-table td { padding: 10px 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
.answer-table tr:nth-child(even) td { background: #f8fafc; }
.answer-table tr.invalid td.num {
  border-left: 4px solid var(--danger); color: var(--danger); font-weight: bold;
}
.answer-table td.num { font-weight: 600; color: #475569; width: 48px; text-align: center; }
.answer-table td.grp { font-weight: 600; color: #1e293b; white-space: nowrap; }
.answer-table td.title { min-width: 240px; }
.answer-table td.title .t { font-weight: 600; color: #0f172a; }
.answer-table td.title .ctx {
  color: #64748b; font-size: 13px; margin-top: 4px;
  border-left: 3px solid #cbd5e1; padding-left: 8px;
}
.answer-table td.memo, .answer-table th:last-child { width: 28%; min-width: 300px; }
.answer-table textarea {
  width: 100%; min-height: 84px; padding: 6px 8px;
  border: 1px solid var(--border); border-radius: 6px;
  font-family: var(--font-stack); font-size: 13px; resize: vertical;
}

/* Yes-No mode */
.yn { padding: 40px 28px; max-width: 720px; margin: 24px auto; }
.yn-title { font-size: 24px; margin-bottom: 12px; text-align: center; }
.yn-ctx { color: #64748b; margin-bottom: 28px; text-align: left; }
.yn-ctx ul, .yn-ctx ol { padding-left: 1.5em; margin: 0.5em 0; }
.yn-ctx li { margin: 0.3em 0; }
.yn-ctx p { margin: 0.5em 0; }
.yn-buttons {
  display: flex; gap: 12px; justify-content: center;
  flex-wrap: wrap; margin-bottom: 24px;
}

/* Wizard mode */
.wiz-stepper {
  display: flex; gap: 8px; padding: 16px 20px;
  background: #f8fafc; border-bottom: 1px solid var(--border);
  align-items: center; margin: -24px -20px 20px;
}
.wiz-step {
  width: 36px; height: 36px; border-radius: 18px; padding: 0;
  border: none; background: #e2e8f0; color: #64748b; font-weight: 600;
  cursor: pointer;
}
.wiz-step.current { background: var(--accent); color: white; }
.wiz-step.answered { background: var(--success); color: white; }
.wiz-prog { margin-left: auto; color: #64748b; font-size: 13px; }
.wiz-page[data-active="false"] { display: none; }
.wiz-nav {
  display: flex; gap: 12px; padding: 12px 20px;
  border-top: 1px solid var(--border); background: #f8fafc;
  margin: 20px -20px -24px;
}
.wiz-nav button { flex: 1; padding: 10px 16px; }
.wiz-nav button:disabled { opacity: 0.5; cursor: not-allowed; }

/* Diff-table mode */
.diff-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.diff-table th {
  background: #1e293b; color: white; padding: 10px;
  text-align: left; font-weight: 600;
}
.diff-table td {
  padding: 12px; border-bottom: 1px solid #e2e8f0;
  vertical-align: top;
}
.diff-table tr:nth-child(even) td { background: #f8fafc; }
.diff-table .t { font-weight: 600; color: #0f172a; margin-bottom: 4px; }
.diff-table .cur {
  color: #374151; font-size: 13px; white-space: pre-wrap; word-break: break-word;
}
.diff-table td.prop.changed { background: #f0fdf4; }
.diff-table td.prop {
  color: #374151; font-size: 13px; white-space: pre-wrap; word-break: break-word;
}
.diff-table textarea {
  width: 100%; min-height: 48px; padding: 6px 8px;
  border: 1px solid var(--border); border-radius: 6px;
  font-family: var(--font-stack); font-size: 13px; resize: vertical;
}
"""

CSS += """
/* ── Markdown body styles ── */
.card .ctx, .ctx-tail, .yn-ctx, .answer-table .ctx { line-height: 1.65; }
.card .ctx p, .ctx-tail p, .yn-ctx p, .answer-table .ctx p { margin: 4px 0; }
.card .ctx ul, .ctx-tail ul, .yn-ctx ul, .answer-table .ctx ul {
  margin: 4px 0; padding-left: 20px;
}
.card .ctx ul li, .ctx-tail ul li, .yn-ctx ul li, .answer-table .ctx ul li {
  margin: 2px 0;
}
.card .ctx blockquote, .ctx-tail blockquote, .yn-ctx blockquote, .answer-table .ctx blockquote {
  border-left: 3px solid #cbd5e1; padding-left: 10px; margin: 6px 0;
  color: var(--text-muted);
}
.card .ctx code, .ctx-tail code, .yn-ctx code, .answer-table .ctx code {
  background: #f1f5f9; padding: 1px 6px; border-radius: 4px;
  font-family: ui-monospace, "SF Mono", "Menlo", "Consolas", monospace;
  font-size: 0.92em;
}
.card .ctx a, .ctx-tail a, .yn-ctx a, .answer-table .ctx a {
  color: var(--accent); text-decoration: underline;
}

/* ── Chip (「」default amber / 『』info blue / 【】good green) ── */
.chip {
  display: inline-block;
  background: #fef3c7; color: #92400e;
  padding: 1px 8px; margin: 0 2px;
  border-radius: 10px; font-size: 0.92em;
  font-weight: 500;
}
.chip.chip-info { background: #dbeafe; color: #1e40af; }
.chip.chip-good { background: #dcfce7; color: #166534; }

/* ── Inline emphasis (bold/strong は subtle navy で色彩を増やす) ── */
.card .ctx strong,
.ctx-tail strong,
.yn-ctx strong,
.answer-table .ctx strong {
  color: #0f172a;
  background: linear-gradient(transparent 62%, #e0e7ff 62%, #e0e7ff 92%, transparent 92%);
  padding: 0 2px;
}

/* ── Collapse (<details>) ── */
.ctx-fold {
  margin: 6px 0; padding: 4px 8px;
  border: 1px dashed var(--border); border-radius: 6px;
  background: rgba(0,0,0,0.015);
}
.ctx-fold > summary {
  cursor: pointer; list-style: revert; color: var(--text);
  padding: 4px 0;
}
.ctx-fold > summary::-webkit-details-marker { color: var(--text-muted); }
.ctx-fold > summary > p { display: inline; margin: 0; }
.ctx-fold[open] > summary { margin-bottom: 8px; }
.ctx-tail { padding-left: 4px; }

/* ── Options (rich) ── */
.opt {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 14px; margin: 6px 0;
  border: 1px solid var(--border); border-radius: 10px;
  cursor: pointer; transition: all 0.12s;
  background: #fff;
  border-left-width: 4px;
}
.opt input[type="radio"] { margin-top: 4px; flex-shrink: 0; }
.opt .opt-body { flex: 1; min-width: 0; }
.opt .opt-head { display: flex; align-items: center; gap: 6px; }
.opt .opt-value { font-weight: 500; }
.opt .star { color: #f59e0b; font-size: 1.1em; }
.opt .effect {
  font-size: 0.88em; color: var(--text-muted); margin-top: 4px;
  line-height: 1.45;
}
.opt:hover { background: #f8fafc; }
.opt:has(input:checked) {
  background: #eff6ff; border-color: var(--accent); color: var(--accent);
}
.opt:has(input:checked) .opt-value { font-weight: 600; }
.opt:has(input:checked) .effect { color: var(--accent); }

/* tone（border-left の色で意味を示す） */
.opt.tone-neutral { border-left-color: #cbd5e1; }
.opt.tone-add { border-left-color: #16a34a; }
.opt.tone-replace { border-left-color: #f59e0b; }
.opt.tone-remove { border-left-color: #dc2626; }
.opt.tone-minimum { border-left-color: #94a3b8; }

/* recommended は subtle な ring */
.opt.recommended {
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.25);
  background: #fffbeb;
}
.opt.recommended:hover { background: #fef3c7; }
.opt.recommended:has(input:checked) {
  background: #eff6ff; box-shadow: 0 0 0 2px var(--accent);
}

/* table 内の .opt は縮小表示 */
.answer-table .opt {
  padding: 5px 10px; margin: 3px 0; font-size: 13px;
}
.answer-table .opt .effect { font-size: 0.85em; }

/* yes-no 内の .opt は大ボタン風 */
.yn-buttons .opt {
  min-width: 200px; padding: 16px 24px;
  flex-direction: column; align-items: center; text-align: center;
  border-left-width: 1px; border: 2px solid var(--border);
}
.yn-buttons .opt input { display: none; }
.yn-buttons .opt .effect { margin-top: 6px; }
.yn-buttons .opt.tone-add { border-color: #16a34a; }
.yn-buttons .opt.tone-replace { border-color: #f59e0b; }
.yn-buttons .opt.tone-remove { border-color: #dc2626; }
.yn-buttons .opt.tone-minimum { border-color: #94a3b8; }
"""


# ─── JS テンプレート ──────────────────────────────────────────────────────

JS_TEMPLATE = """
const PAYLOAD_KIND = "__KIND__";
const $ = (s) => document.querySelector(s);

function collectItems() {
  const cards = document.querySelectorAll('.card[data-id], tr.row[data-id]');
  return Array.from(cards).map(el => {
    const id = el.dataset.id;
    const choiceEl = el.querySelector(`input[name="choice-${id}"]:checked`);
    const memoEl = el.querySelector(`textarea[name="memo-${id}"]`);
    return {
      id,
      choice: choiceEl ? choiceEl.value : "",
      memo: memoEl ? memoEl.value.trim() : "",
    };
  });
}

function collectDiffRows() {
  return Array.from(document.querySelectorAll('.diff-row')).map(tr => {
    const id = tr.dataset.id;
    const approved = tr.querySelector(`input[name="approved-${id}"]`).checked;
    const proposed = tr.dataset.proposed;
    const memoEl = tr.querySelector(`textarea[name="memo-${id}"]`);
    const memo = memoEl ? memoEl.value.trim() : "";
    return { id, approved, value: approved ? proposed : "", memo };
  });
}

function validate() {
  const items = document.querySelectorAll('.card[data-id], tr.row[data-id]');
  let invalid = 0;
  items.forEach(el => {
    el.classList.remove('invalid');
    const id = el.dataset.id;
    const hasOptions = el.querySelector(`input[name="choice-${id}"]`);
    if (!hasOptions) return;
    const choice = el.querySelector(`input[name="choice-${id}"]:checked`);
    const memoEl = el.querySelector(`textarea[name="memo-${id}"]`);
    const memo = memoEl ? memoEl.value.trim() : "";
    if (!choice && !memo) {
      el.classList.add('invalid');
      invalid++;
    }
  });
  return invalid;
}

async function doSubmit() {
  let body;
  if (PAYLOAD_KIND === "rows") {
    body = collectDiffRows();
  } else {
    const invalid = validate();
    if (invalid > 0) {
      const s = $('#status');
      s.textContent = `${invalid} 問が未回答です（選択 or メモ記入が必要）`;
      s.className = 'status error';
      return;
    }
    body = collectItems();
  }
  await fetch('/submit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  window.__SUBMITTED__ = true;
  // --app=URL で開かれたウィンドウは window.close() で閉じれる。
  // 普通のタブで閉じれない場合のみフォールバックを表示。
  window.close();
  setTimeout(() => {
    if (!window.closed) {
      document.body.innerHTML = '<div style="padding:48px;text-align:center;font-family:system-ui;font-size:16px;color:#16a34a;">✓ 送信しました。このタブを閉じてください。</div>';
    }
  }, 200);
}

async function doCancel() {
  if (!confirm('回答を破棄して終了しますか？')) return;
  await fetch('/cancel', {method: 'POST'});
  window.__CANCELLED__ = true;
  window.close();
  setTimeout(() => {
    if (!window.closed) {
      document.body.innerHTML = '<div style="padding:48px;text-align:center;font-family:system-ui;font-size:16px;color:#64748b;">キャンセルしました。このタブを閉じてください。</div>';
    }
  }, 200);
}

document.addEventListener('DOMContentLoaded', () => {
  const submitBtn = $('#submit-btn');
  const cancelBtn = $('#cancel-btn');
  if (submitBtn) submitBtn.addEventListener('click', doSubmit);
  if (cancelBtn) cancelBtn.addEventListener('click', doCancel);

  // wizard mode (Task 6 で詳細)
  const wizPages = document.querySelectorAll('.wiz-page');
  if (wizPages.length > 0) initWizard(wizPages);
});

function initWizard(wizPages) {
  const wizSteps = document.querySelectorAll('.wiz-step');
  const wizPrev = $('#wiz-prev');
  const wizNext = $('#wiz-next');
  const wizProg = document.querySelector('.wiz-prog');
  let current = 0;

  function refreshAnswered() {
    wizPages.forEach((page, i) => {
      const card = page.querySelector('.card');
      if (!card) return;
      const id = card.dataset.id;
      const choice = page.querySelector(`input[name="choice-${id}"]:checked`);
      const memoEl = page.querySelector(`textarea[name="memo-${id}"]`);
      const memo = memoEl ? memoEl.value.trim() : "";
      if (i !== current) {
        wizSteps[i].classList.toggle('answered', !!(choice || memo));
      }
    });
  }

  function go(idx) {
    current = idx;
    wizPages.forEach((p, i) => p.dataset.active = i === idx ? "true" : "false");
    wizSteps.forEach((s, i) => s.classList.toggle('current', i === idx));
    if (wizProg) wizProg.textContent = `${idx + 1}/${wizPages.length}`;
    wizPrev.disabled = idx === 0;
    wizNext.textContent = idx === wizPages.length - 1 ? "Submit" : "次へ →";
    refreshAnswered();
  }

  wizSteps.forEach((s, i) => s.addEventListener('click', () => go(i)));
  wizPrev.addEventListener('click', () => current > 0 && go(current - 1));
  wizNext.addEventListener('click', () => {
    if (current === wizPages.length - 1) doSubmit();
    else go(current + 1);
  });
  document.addEventListener('input', refreshAnswered);
}

window.addEventListener('beforeunload', () => {
  if (window.__SUBMITTED__ || window.__CANCELLED__) return;
  // タブ閉じ / window 閉じは cancel として扱う
  navigator.sendBeacon('/cancel');
});
"""


def render_js(payload, mode, kind) -> str:
    return JS_TEMPLATE.replace("__KIND__", kind)


# ─── Markdown renderer (stdlib のみ) ─────────────────────────────────────


def _render_inline(text: str) -> str:
    """Raw (unescaped) text → HTML with inline markup applied.
    HTML-escape は内部で先に行うので呼び出し側で esc 不要。
    """
    s = html_lib.escape(text, quote=True)
    # bold: **x** → <strong>x</strong>
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    # code: `x` → <code>x</code>
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    # link: [text](https://...) → <a href="..." target="_blank">text</a>
    s = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        s,
    )
    # 「...」chip 化（最外側のカギカッコのみ・ネスト非対応で十分）
    s = re.sub(r"「([^」]+)」", r'<span class="chip">\1</span>', s)
    # 『...』 = info chip（青系・トピック・分類）
    s = re.sub(r"『([^』]+)』", r'<span class="chip chip-info">\1</span>', s)
    # 【...】 = good chip（緑系・推奨・ポジティブ）
    s = re.sub(r"【([^】]+)】", r'<span class="chip chip-good">\1</span>', s)
    return s


def _split_blocks(text: str) -> list[str]:
    """空行で段落を分割。前後の空白は trim。"""
    return [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]


def _render_block(block: str) -> str:
    """1 段落を HTML ブロックに。bullet list / blockquote / paragraph を判別。

    1 ブロック内で「prefix paragraph + bullets」が空行なしで連続するケースも捌く
    (例: 'intro:\\n- A\\n- B' のように blank line なしで bullets が続く形)。
    """
    lines = [l for l in block.split("\n") if l.strip()]
    if not lines:
        return ""
    if all(l.lstrip().startswith("- ") for l in lines):
        items = "\n".join(
            f"  <li>{_render_inline(l.lstrip()[2:])}</li>" for l in lines
        )
        return f"<ul>\n{items}\n</ul>"
    if all(l.lstrip().startswith(">") for l in lines):
        # > 以降を取得（> も >  も対応）
        body_lines = [l.lstrip()[1:].lstrip() for l in lines]
        body = "<br>".join(_render_inline(l) for l in body_lines)
        return f"<blockquote>{body}</blockquote>"
    # mixed: prefix paragraph + bullets (空行なしで - 行が続く)
    has_bullet = any(l.lstrip().startswith("- ") for l in lines)
    if has_bullet:
        prefix_lines = []
        bullet_lines = []
        for l in lines:
            if l.lstrip().startswith("- "):
                bullet_lines.append(l)
            elif bullet_lines:
                # bullets 後の続き行は最後の <li> に連結（lazy continuation）
                bullet_lines[-1] = bullet_lines[-1] + " " + l.strip()
            else:
                prefix_lines.append(l)
        parts = []
        if prefix_lines:
            joined = " ".join(l.strip() for l in prefix_lines)
            parts.append(f"<p>{_render_inline(joined)}</p>")
        if bullet_lines:
            items = "\n".join(
                f"  <li>{_render_inline(l.lstrip()[2:])}</li>" for l in bullet_lines
            )
            parts.append(f"<ul>\n{items}\n</ul>")
        return "\n".join(parts)
    # plain paragraph
    joined = " ".join(l.strip() for l in lines)
    return f"<p>{_render_inline(joined)}</p>"


def render_markdown(text: str) -> str:
    """stdlib のみで minimal Markdown → HTML。
    対応: 段落 / **bold** / `code` / [text](url)。
    Task 2: + bullet list / blockquote, Task 3: + 「」chip。
    """
    if not text:
        return ""
    blocks = _split_blocks(text)
    return "\n".join(_render_block(b) for b in blocks)


COLLAPSE_CHAR_THRESHOLD = 240
COLLAPSE_PARA_THRESHOLD = 3


def should_collapse(text: str) -> tuple[bool, str, str]:
    """長文 context を折りたたむべきか判定。
    返り値: (collapse, head, tail)。collapse=False なら tail は空、head は全文。

    ルール:
      - TL;DR: 行があれば → 折りたたむ（先頭行 head、残り tail）
      - bullet list (- ...) を含む → 折りたたまない（構造化されてる）
      - 段落数 >= COLLAPSE_PARA_THRESHOLD or 総字数 > COLLAPSE_CHAR_THRESHOLD → 折りたたむ
    """
    if not text:
        return False, "", ""

    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("TL;DR:"):
        head = lines[0]
        tail = "\n".join(lines[1:]).lstrip("\n")
        return True, head, tail

    paras = _split_blocks(text)
    has_bullet = any(
        all(l.lstrip().startswith("- ") for l in p.split("\n") if l.strip())
        for p in paras
    )
    if has_bullet:
        return False, text, ""

    long_enough = len(text) > COLLAPSE_CHAR_THRESHOLD or len(paras) >= COLLAPSE_PARA_THRESHOLD
    if long_enough and len(paras) >= 2:
        head = paras[0]
        tail = "\n\n".join(paras[1:])
        return True, head, tail
    return False, text, ""


VALID_TONES = {"neutral", "add", "replace", "remove", "minimum"}


def normalize_option(opt) -> dict:
    """文字列 / object どちらの options 要素も dict に正規化。"""
    if isinstance(opt, str):
        return {"value": opt, "recommended": False, "tone": "neutral", "effect": ""}
    if not isinstance(opt, dict) or "value" not in opt:
        raise ValueError(f"option は文字列 or {{value, ...}} の dict: {opt!r}")
    tone = opt.get("tone", "neutral")
    if tone not in VALID_TONES:
        tone = "neutral"
    return {
        "value": opt["value"],
        "recommended": bool(opt.get("recommended", False)),
        "tone": tone,
        "effect": opt.get("effect", "") or "",
    }


def render_option(opt, item_id: str, name: str) -> str:
    """1 個の選択肢を <label class="opt ..."><input radio>...</label> に。"""
    o = normalize_option(opt)
    value = o["value"]
    classes = ["opt", f"tone-{o['tone']}"]
    if o["recommended"]:
        classes.append("recommended")
    star = '<span class="star" aria-label="推奨">★</span>' if o["recommended"] else ""
    effect_html = f'<div class="effect">{esc(o["effect"])}</div>' if o["effect"] else ""
    return (
        f'<label class="{" ".join(classes)}">'
        f'<input type="radio" name="{esc(name)}" value="{esc(value)}">'
        f'<div class="opt-body">'
        f'<div class="opt-head">{star}<span class="opt-value">{esc(value)}</span></div>'
        f'{effect_html}'
        f'</div>'
        f'</label>'
    )


# ─── HTML escape ──────────────────────────────────────────────────────────

def esc(s) -> str:
    """HTML エスケープ。None は空文字。属性値にも使えるよう quote=True。"""
    if s is None:
        return ""
    return html_lib.escape(str(s), quote=True)


# ─── render_card ──────────────────────────────────────────────────────────

def render_card(item: dict, idx: int) -> str:
    item_id = item["id"]
    title = esc(item.get("title", "(no title)"))
    context_raw = item.get("context", "") or ""
    options = item.get("options", []) or []
    memo_label = esc(item.get("memo_label", "補足"))

    # context: Markdown 描画 + 必要なら details で折りたたみ
    if context_raw:
        collapse, head, tail = should_collapse(context_raw)
        if collapse and tail:
            ctx_html = (
                '<details class="ctx-fold">'
                f'<summary>{render_markdown(head)}</summary>'
                f'<div class="ctx-tail">{render_markdown(tail)}</div>'
                '</details>'
            )
        else:
            ctx_html = f'<div class="ctx">{render_markdown(context_raw)}</div>'
    else:
        ctx_html = ""

    # options: 文字列 / object どちらも render_option で統一
    if options:
        opts_html = "\n".join(
            "    " + render_option(opt, item_id, f"choice-{item_id}")
            for opt in options
        )
    else:
        opts_html = (
            '    <p style="color:#94a3b8;font-style:italic;margin:8px 0;">'
            '（自由記述: 下のメモに記入）</p>'
        )

    return f"""
<section class="card" data-id="{esc(item_id)}">
  <h2>Q{idx}. {title}</h2>
{ctx_html}
  <div class="opts">
{opts_html}
  </div>
  <div class="memo-wrap">
    <div class="memo-label">{memo_label}</div>
    <textarea name="memo-{esc(item_id)}" rows="3"></textarea>
  </div>
</section>"""


# ─── render_table ────────────────────────────────────────────────────────

def render_table(items: list[dict]) -> str:
    has_group = any((it.get("group") or "").strip() for it in items)

    head_cells = ['<th>#</th>']
    if has_group:
        head_cells.append('<th>PJ</th>')
    head_cells.extend(['<th>件名・状況</th>', '<th>選択肢</th>', '<th>メモ</th>'])
    head = "<thead><tr>" + "".join(head_cells) + "</tr></thead>"

    body_rows = []
    prev_group = None
    for i, item in enumerate(items, 1):
        item_id = item["id"]
        title = esc(item.get("title", ""))
        context_raw = item.get("context", "") or ""
        ctx_html = render_markdown(context_raw) if context_raw else ""
        options = item.get("options", []) or []
        memo_label = esc(item.get("memo_label", "補足"))

        cur_group = (item.get("group") or "").strip() if has_group else None
        show_group = cur_group if cur_group != prev_group else ""
        prev_group = cur_group

        if options:
            opt_html = "\n".join(
                f'    {render_option(opt, item_id, f"choice-{item_id}")}'
                for opt in options
            )
        else:
            opt_html = f'<em style="color:#94a3b8;">（{memo_label} に記入）</em>'

        cells = [f'<td class="num">Q{i}</td>']
        if has_group:
            cells.append(f'<td class="grp">{esc(show_group)}</td>')
        cells.append(
            f'<td class="title"><div class="t">{title}</div>'
            + (f'<div class="ctx">{ctx_html}</div>' if ctx_html else "")
            + "</td>"
        )
        cells.append(f'<td class="opts">{opt_html}</td>')
        cells.append(
            f'<td class="memo"><textarea name="memo-{esc(item_id)}" rows="3"></textarea></td>'
        )
        body_rows.append(
            f'<tr class="row" data-id="{esc(item_id)}">' + "".join(cells) + "</tr>"
        )

    return (
        '<table class="answer-table">'
        + head
        + "<tbody>" + "\n".join(body_rows) + "</tbody>"
        + "</table>"
    )


# ─── render_yes_no ───────────────────────────────────────────────────────

def render_yes_no(item: dict) -> str:
    item_id = esc(item["id"])
    title = esc(item.get("title", ""))
    context_raw = item.get("context", "") or ""
    options = item.get("options", []) or []
    memo_label = esc(item.get("memo_label", "補足"))

    ctx_html = (
        f'<div class="yn-ctx">{render_markdown(context_raw)}</div>'
        if context_raw else ""
    )

    btn_html = "\n".join(
        f'    {render_option(opt, item["id"], f"choice-{item_id}")}'
        for opt in options
    )

    return f"""
<section class="card yn" data-id="{item_id}">
  <h2 class="yn-title">{title}</h2>
  {ctx_html}
  <div class="yn-buttons">
{btn_html}
  </div>
  <div class="memo-wrap">
    <div class="memo-label">{memo_label}（任意）</div>
    <textarea name="memo-{item_id}" rows="2"></textarea>
  </div>
</section>"""


# ─── render_wizard ───────────────────────────────────────────────────────

def render_wizard(items: list[dict]) -> str:
    n = len(items)
    steps = "\n".join(
        f'<button type="button" class="wiz-step{" current" if i == 0 else ""}" '
        f'data-idx="{i}">{i + 1}</button>'
        for i in range(n)
    )
    pages = "\n".join(
        f'<div class="wiz-page" data-idx="{i}" data-active="{"true" if i == 0 else "false"}">'
        + render_card(it, i + 1)
        + '</div>'
        for i, it in enumerate(items)
    )
    return f"""
<div class="wiz-stepper">{steps}<span class="wiz-prog">1/{n}</span></div>
<div class="wiz-pages">{pages}</div>
<div class="wiz-nav">
  <button type="button" id="wiz-prev" disabled>← 戻る</button>
  <button type="button" id="wiz-next" class="primary">次へ →</button>
</div>"""


# ─── render_diff_table ───────────────────────────────────────────────────

def render_diff_table(rows: list[dict]) -> str:
    head = (
        '<thead><tr><th></th><th>項目 / 現在値</th>'
        '<th>提案値</th><th>メモ</th></tr></thead>'
    )
    body_rows = []
    for row in rows:
        rid = esc(row["id"])
        label = esc(row.get("label", row["id"]))
        current = row.get("current", "") or ""
        proposed = row.get("proposed", "") or ""
        changed = current != proposed

        cur_disp = esc(current) if current else '<em style="color:#94a3b8;">（未設定）</em>'
        prop_disp = esc(proposed) if proposed else '<em style="color:#94a3b8;">（未設定）</em>'

        cur_style = (
            ' style="text-decoration:line-through;color:#475569;"' if changed and current else ""
        )
        prop_style = (
            ' style="color:#15803d;font-weight:600;"' if changed and proposed else ""
        )

        body_rows.append(f"""
<tr class="diff-row" data-id="{rid}" data-changed="{'true' if changed else 'false'}" data-proposed="{esc(proposed)}">
  <td><input type="checkbox" name="approved-{rid}" checked></td>
  <td><div class="t">{label}</div><div class="cur"{cur_style}>{cur_disp}</div></td>
  <td class="prop{(' changed' if changed else '')}"{prop_style}>{prop_disp}</td>
  <td><textarea name="memo-{rid}" rows="2"></textarea></td>
</tr>""")
    return (
        '<table class="diff-table">' + head
        + '<tbody>' + "\n".join(body_rows) + '</tbody></table>'
    )


# ─── render_html (top-level dispatcher) ──────────────────────────────────

def render_html(payload, mode, kind, title="draft:answer-gui") -> str:
    if mode == "card":
        body = "\n".join(render_card(it, i + 1) for i, it in enumerate(payload))
    elif mode == "table":
        body = render_table(payload)
    elif mode == "yes-no":
        body = render_yes_no(payload[0])
    elif mode == "wizard":
        body = render_wizard(payload)
    elif mode == "diff-table":
        body = render_diff_table(payload)
    else:
        body = f'<p>mode "{esc(mode)}" は未実装</p>'

    js = render_js(payload, mode, kind)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body data-mode="{esc(mode)}">
<div class="container">
  <h1 class="page-title">{esc(title)}</h1>
  <form id="answer-form">
{body}
  </form>
</div>
<footer class="footer">
  <div class="status" id="status">{len(payload)} 問</div>
  <button type="button" id="cancel-btn">Cancel</button>
  <button type="button" id="submit-btn" class="primary">Submit</button>
</footer>
<script>{js}</script>
</body>
</html>"""


def pick_port() -> int:
    """OS に空きポートを選ばせる（衝突ゼロ・KISS）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_browser_command(candidates: list[str]) -> str | None:
    """candidates の中から最初に見つかったブラウザの絶対パスを返す。
    絶対パスが存在すればそのまま返し、なければ shutil.which でコマンド名を解決する。
    """
    for c in candidates:
        if os.path.exists(c):
            return c
        which = shutil.which(c)
        if which:
            return which
    return None


# ─── ブラウザ起動（3-tier fallback） ──────────────────────────────────────

CHROMIUM_LIKE = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Arc.app/Contents/MacOS/Arc",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome", "chromium", "chromium-browser",
    "msedge", "chrome.exe", "msedge.exe",
]

FIREFOX_LIKE = [
    "/Applications/Firefox.app/Contents/MacOS/firefox",
    "firefox", "firefox.exe",
]


def open_window(url: str) -> str:
    """3-tier fallback で必ず new window 起動。使ったブラウザ種別を返す。

    Tier 1: Chromium 系 --app=URL（独立窓・URL バーなし・Dock 別アイコン）
    Tier 2: Firefox -new-window URL（独立窓・URL バーあり）
    Tier 3: webbrowser.open_new(url)（Safari 等・new window 試行）
    """
    chrome = find_browser_command(CHROMIUM_LIKE)
    if chrome:
        subprocess.Popen(
            [chrome, f"--app={url}", "--new-window"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return "chromium-app"
    firefox = find_browser_command(FIREFOX_LIKE)
    if firefox:
        subprocess.Popen(
            [firefox, "-new-window", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return "firefox"
    webbrowser.open_new(url)
    return "fallback"


def normalize_input(raw) -> tuple[str | None, list[dict], str]:
    """list / object どちらでも (mode, payload, kind) に正規化。
    kind: "items" = 通常質問、"rows" = diff-table 用
    """
    if isinstance(raw, list):
        return None, raw, "items"
    if isinstance(raw, dict):
        mode = raw.get("mode")
        if "rows" in raw:
            return mode, raw["rows"], "rows"
        if "items" in raw:
            return mode, raw["items"], "items"
        raise ValueError("object 形式には 'items' または 'rows' キーが必要です")
    raise ValueError("入力は配列または {mode, items|rows} の object である必要があります")


def validate(payload: list[dict], kind: str) -> tuple[bool, str]:
    if not isinstance(payload, list) or not payload:
        return False, "入力は非空の配列である必要があります"
    if kind == "rows":
        for i, row in enumerate(payload):
            if not isinstance(row, dict):
                return False, f"rows[{i}] は object である必要があります"
            for key in ("id", "label", "current", "proposed"):
                if key not in row:
                    return False, f"rows[{i}] に必須キー '{key}' がありません"
    else:
        for i, item in enumerate(payload):
            if not isinstance(item, dict):
                return False, f"items[{i}] は object である必要があります"
            if "id" not in item or "title" not in item:
                return False, f"items[{i}] に必須キー id / title がありません"
            if "options" in item and not isinstance(item["options"], list):
                return False, f"items[{i}].options は配列である必要があります"
    return True, ""


def _should_use_table(items: list[dict]) -> bool:
    if len(items) < 4:
        return False
    has_options = sum(1 for it in items if it.get("options"))
    return has_options / len(items) >= 0.75


def auto_layout(items: list[dict]) -> str:
    return "table" if _should_use_table(items) else "card"


# ─── HTTP server ─────────────────────────────────────────────────────────

def make_handler(payload, mode, kind, title, result):
    html_body = render_html(payload, mode, kind, title)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # サーバログ抑制

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, html_body, "text/html; charset=utf-8")
            else:
                self._send(404, "Not Found", "text/plain; charset=utf-8")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            if self.path == "/submit":
                try:
                    data = json.loads(body) if body else []
                except json.JSONDecodeError as e:
                    self._send(400, f"invalid json: {e}", "text/plain; charset=utf-8")
                    return
                result["status"] = "submitted"
                result["data"] = data
                self._send(200, '{"ok":true}', "application/json")
            elif self.path == "/cancel":
                result["status"] = "cancelled"
                self._send(200, '{"ok":true}', "application/json")
            else:
                self._send(404, "Not Found", "text/plain; charset=utf-8")

        def _send(self, status, body, ctype):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def start_server(payload, mode, kind, title):
    """サーバを起動し、(server, port, result_dict) を返す。
    result_dict は {"status": "pending" | "submitted" | "cancelled", "data": ...}。
    """
    port = pick_port()
    result = {"status": "pending", "data": None}
    handler_cls = make_handler(payload, mode, kind, title, result)
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._thread = thread  # 参照保持
    return server, port, result


TIMEOUT_SEC = 30 * 60  # 30 分操作なしで自動キャンセル


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--layout", dest="layout_override", default=None)
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    try:
        args = parser.parse_args()
    except SystemExit:
        print(__doc__, file=sys.stderr)
        return 2

    in_path = Path(args.input_path)
    out_path = Path(args.output_path)

    try:
        raw = json.loads(in_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"入力ファイルが見つかりません: {in_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"入力 JSON が不正: {e}", file=sys.stderr)
        return 2

    try:
        json_mode, payload, kind = normalize_input(raw)
    except ValueError as e:
        print(f"入力フォーマットエラー: {e}", file=sys.stderr)
        return 2

    ok, err = validate(payload, kind)
    if not ok:
        print(f"入力検証エラー: {err}", file=sys.stderr)
        return 2

    # mode 解決: --layout > JSON mode > kind=rows なら diff-table > 自動判定
    if args.layout_override:
        mode = args.layout_override
    elif json_mode:
        mode = json_mode
    elif kind == "rows":
        mode = "diff-table"
    else:
        mode = auto_layout(payload)

    if mode not in IMPLEMENTED_MODES:
        print(
            f"レイアウト '{mode}' は未実装（実装済み: {', '.join(sorted(IMPLEMENTED_MODES))}）",
            file=sys.stderr,
        )
        return 2

    # title: object 形式の "title" を尊重、なければデフォルト
    title = (
        raw.get("title") if isinstance(raw, dict) and raw.get("title")
        else "draft:answer-gui"
    )

    server, port, result = start_server(payload, mode, kind, title)
    url = f"http://127.0.0.1:{port}/"
    if os.environ.get("PSD_ANSWER_GUI_NO_BROWSER") == "1":
        # E2E テスト用: ブラウザを開かずに URL だけ表示
        print(f"[draft:answer-gui] NO_BROWSER mode — URL: {url}", file=sys.stderr)
    else:
        browser_kind = open_window(url)
        print(
            f"[draft:answer-gui] {browser_kind} で {url} を起動しました（mode={mode}, {len(payload)} 件）",
            file=sys.stderr,
        )

    # 結果待ち（タイムアウト付き）
    import time
    start = time.monotonic()
    while result["status"] == "pending":
        if time.monotonic() - start > TIMEOUT_SEC:
            server.shutdown()
            print("タイムアウト（30 分無応答）", file=sys.stderr)
            return 1
        time.sleep(0.2)

    server.shutdown()

    if result["status"] == "submitted":
        out_path.write_text(
            json.dumps(result["data"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    return 1  # cancelled


if __name__ == "__main__":
    sys.exit(main())
