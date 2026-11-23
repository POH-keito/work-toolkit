# draft:answer-gui デザイントークン

`scripts/answer_gui.py` 内の **`CSS` 定数** が唯一の真実（SSOT）。配色・タイポ・スペーシングを変更する場合はここを編集する。

## Design Direction: Refined Minimalism

確認 UI は意思決定を補助するツール。
派手な演出は判断を遅らせる → "intentionality, not intensity" 原則。

- ✅ 余白と階層で情報の優先度を示す
- ✅ アクセントは 1 色（accent）＋意味色（danger/success）のみ
- ✅ micro-interaction は最小（hover transition のみ）
- ❌ 多段アニメーション、グラデーション背景、装飾ボーダー

## CSS Variables（`:root` で定義）

| 変数 | 値 | 用途 |
|---|---|---|
| `--font-stack` | `system-ui, -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic UI", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", sans-serif` | OS ネイティブフォント（macOS: SF / Win: Segoe UI / Linux: 系統 sans） |
| `--bg` | `#ffffff` | ページ背景 |
| `--surface` | `#fafafa` | カード背景 |
| `--border` | `#e5e7eb` | カード枠・区切り |
| `--text` | `#1a1a1a` | 本文 |
| `--text-muted` | `#6b7280` | サブテキスト |
| `--accent` | `#2563eb` | プライマリ・選択中ラジオ |
| `--accent-hover` | `#1d4ed8` | hover |
| `--danger` | `#dc2626` | 未回答・エラー |
| `--success` | `#16a34a` | 完了・wizard ステッパー回答済み |

## タイポ

- 本文サイズ: `15px`、line-height: `1.55`
- ページタイトル `h1.page-title`: `22px / 600`
- カード見出し `h2`: `16px / 600`
- 補足/コンテキスト: `13px`、`--text-muted`

## レイアウト

- `.container` max-width: `920px`
- ボタン padding: `8px 18px`、radius: `8px`
- カード padding: `18px 20px`、radius: `12px`
- フッター固定: `position: fixed`、backdrop-filter blur

## Chip / Tone Palette（v2 追加）

| 用途 | 色 | hex |
|---|---|---|
| chip 背景（amber） | yellow-100 | `#fef3c7` |
| chip 文字 | amber-800 | `#92400e` |
| star（推奨マーク） | amber-500 | `#f59e0b` |
| tone-add（追加・採用） | green-600 | `#16a34a` |
| tone-replace（置換・条件付き） | amber-500 | `#f59e0b` |
| tone-remove（削除・棄却） | red-600 | `#dc2626` |
| tone-minimum（最低限・無関心） | slate-400 | `#94a3b8` |
| tone-neutral（無色） | slate-300 | `#cbd5e1` |
| recommended ring | amber-500 25%透明 | `rgba(245, 158, 11, 0.25)` |

## なぜ HTML/CSS か（旧 QSS からの転換）

PySide6 QSS は OS によってフォント解決が安定しなかった（HackGen 推し → ない場合フォールバック）。HTML の system font stack はブラウザが OS 標準フォントを自動解決するため、**macOS/Windows/Linux のいずれでも標準的な見た目**になる。CSS `:has()` で selector が直感的に書ける利点もある。
