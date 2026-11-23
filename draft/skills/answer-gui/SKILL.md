---
description: 直前の Claude の確認質問・差分提示を **ローカル HTTP サーバ + ブラウザ** でまとめて回答するスキル（Python 標準ライブラリのみ・依存ゼロ）。Claude が複数論点（質問・選択・差分テーブル）を提示し、ユーザーから一括で回答が必要なときに使用。質問が3件以上、または差分テーブル形式で提案を確認したい場合に強く推奨。
allowed-tools: Read, Write, Edit, Glob, Bash(python3:*), Bash(ls:*), Bash(rm:*)
---

# draft:answer-gui

直前のあなた（Claude）の確認質問を JSON 化し、**ローカル HTTP サーバを立ててブラウザの new window** でユーザーに回答してもらう（依存ゼロ・Python stdlib のみ）。

## 起動条件

直前のアシスタント発話に「**確認したいポイント**」「**論点**」「**Q:**」「A) / B) / C) のような選択肢」「`?` で終わる文」のいずれかがあること。
無ければユーザーに「直前の質問が見つかりません。論点を直接書いて渡してください」と返して終了する。

## 処理フロー

### Step 1: 論点抽出（plan-fb 準拠）

直前のあなた（Claude）のメッセージから論点を抽出し、以下の JSON 形式に変換する。

**抽出パターン**（plan-fb の壁打ちフォーマットに揃える）:

| パターン | 抽出方法 |
|---|---|
| `### #N タイトル` + `Q:` + `- A)` 形式 | そのまま |
| 番号付きリストで論点列挙 + 各項目に選択肢 | リスト 1 項目 = 1 質問 |
| 「**論点**」「**確認したいポイント**」見出しの下のリスト | 見出し下のサブセクションを 1 質問ずつ |
| `?` で終わる文 + 直後に `- A) / - B)` | Q + options |
| 「A or B」「a vs b」表現 | options=[A,B] で 1 問化 |
| 選択肢が見当たらない自由記述質問 | options=[] で出す（自由記述カードになる） |

**JSON スキーマ**:

```json
[
  {
    "id": "q1",
    "title": "短い見出し（30字以内）",
    "context": "Claude が提示した背景・選択肢の補足・対応案",
    "options": ["A: ...", "B: ...", "C: ..."],
    "memo_label": "補足"
  }
]
```

ルール:

- `id` は `q1` `q2` ... の連番
- `options` の各要素は **そのまま GUI ラジオに表示される**ので、ユーザーが見て即決できる文言にする（A/B 記号 + 短い説明）
- 選択肢が定まらない論点は `options: []` にする → 自由記述カードになる
- 1 質問は 1 判断（plan-fb と同じ KISS 原則）

---

## diff-table モード（ist:sync 等での差分確認用）

Q&A カードの代わりに、「現在値 vs 更新後」の比較テーブルを表示する。  
ist:sync などで Notion フィールドの変更確認に使う。

**入力 JSON スキーマ**:

```json
{
  "mode": "diff-table",
  "title": "ist:sync — 更新内容確認",
  "rows": [
    { "id": "summary", "label": "summary", "current": "旧テキスト", "proposed": "新テキスト" },
    { "id": "due",     "label": "due",     "current": "2026-04-27", "proposed": "2026-05-05" },
    { "id": "start",   "label": "start",   "current": "",           "proposed": "" }
  ]
}
```

- `current` / `proposed` が空文字 → セルに「（未設定）」と表示
- 80字超のテキストは `<details>` で折りたたみ
- チェックボックスで行ごとに反映/スキップを選択（デフォルト: 全チェック）

**出力 JSON**:

```json
[
  { "id": "summary", "approved": true,  "value": "新テキスト" },
  { "id": "due",     "approved": true,  "value": "2026-05-05" },
  { "id": "start",   "approved": false, "value": "" }
]
```

`approved: false` の行は `value` が空文字。ist:sync 側で `approved: true` の行だけ write_notion.py に渡す。

---

### Step 2: コンテキスト判定（PLAN.md 追記モード or CLI 戻しモード）

以下の条件で **PLAN.md 追記モード** にする：

1. ユーザーが引数で `_draft/...` パスを指定した
2. セッション中で `_draft/YYYY-MM-DD_xxx/PLAN.md` が活性化している（直近で読んだ／編集した PLAN.md がある）
3. 現在の作業ディレクトリ直下に `_draft/` プレフィックスのフォルダが 1 つだけある（曖昧性なし）

それ以外は **CLI 戻しモード**。

迷う場合はユーザーに聞かず、CLI 戻しモードで進める（後から PLAN.md にコピーは可能）。

### Step 3: ブラウザで回答ウィンドウを開く

> ⚠️ **並列セッション対策**: `/tmp/draft_answer_in.json` のような固定パスは複数 draft:answer-gui が
> 同時起動した際に上書きされる。**必ず `uuidgen` で session ID を生成してパスに埋め込む**こと。

```bash
# 並列セッション衝突を防ぐため、必ず session ID をパスに含める
SESSION_ID=$(uuidgen | tr -d - | head -c 8)
INPUT=/tmp/draft_answer_${SESSION_ID}_in.json
OUTPUT=/tmp/draft_answer_${SESSION_ID}_out.json

# 抽出した JSON を $INPUT に Write tool で書き出す。その後:
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/answer_gui.py" "$INPUT" "$OUTPUT"
# Windows PowerShell の場合:
# $SESSION_ID = ([guid]::NewGuid().ToString('N').Substring(0,8))
# $INPUT = "$env:TEMP\draft_answer_${SESSION_ID}_in.json"
# $OUTPUT = "$env:TEMP\draft_answer_${SESSION_ID}_out.json"
# python "$env:CLAUDE_PLUGIN_ROOT\scripts\answer_gui.py" $INPUT $OUTPUT
```

> 💡 **推奨: Bash の `run_in_background=true` で起動する**
> 同期で待つと Claude はユーザーの回答中ブロックされる。background で起動すれば Claude は他のタスクに着手でき、ユーザーが Submit したら通知 + output JSON が読める。
>
> ```
> Bash(run_in_background=true, command="python3 ...answer_gui.py $INPUT $OUTPUT")
> ```
>
> 完了通知が来たら output JSON を `cat $OUTPUT` で受け取り、後続処理に進む。
> Submit 後、ブラウザウィンドウは `window.close()` で自動的に閉じる（フォールバックメッセージは閉じれない環境のみ表示）。

スクリプトは Python 標準ライブラリのみで動作する。`127.0.0.1` のランダム空きポートで HTTP サーバを起動 → **自動でブラウザの new window が立ち上がる**：

| Tier | ブラウザ | 起動方式 | UI |
|---|---|---|---|
| 1 | Chrome / Edge / Arc / Brave | `--app=URL --new-window` | URL バー・タブバーなしの**独立アプリ窓**（Dock/Taskbar に別アイコン） |
| 2 | Firefox | `-new-window URL` | URL バーあり独立窓 |
| 3 | それ以外 (Safari 等) | `webbrowser.open_new` | new window 試行（OS 設定次第） |

ユーザーが Submit すると output JSON が書かれ、サーバは自走終了する。

- 終了コード 0: ユーザーが Submit。`$OUTPUT` に回答 JSON が入る
- 終了コード 1: ユーザーが Cancel またはタブ/ウィンドウを閉じた → 「キャンセルされました」と返して終了
- 終了コード 2: 入力 JSON エラー → エラー内容を表示してリトライ
- 30 分操作なしで自動キャンセル（exit 1）

**バリデーション仕様**: `options` ありの問でも、memo に記入があれば選択肢未選択のまま Submit できる（提示した選択肢がどれもイケてない時の脱出口）。choice も memo も空のカードのみ赤枠でハイライトされる。diff-table モードはバリデーションなし。

### Step 4: 回答処理

#### CLI 戻しモード

回答 JSON をチャットに反映し、各論点について短く確認:

```
GUI で回答を受け取りました。

- Q1 配置場所: draft:answer-gui （補足: 〜）
- Q2 抽出精度: a 自動 + plan-fb 参考
- ...

この方針で続けます。
```

そのまま元のタスク（質問前にやろうとしていた作業）に戻って続行する。

#### PLAN.md 追記モード

PLAN.md 末尾に **plan-fb と同じフォーマット** で追記する:

```markdown
## #YYYY-MM-DD answer-gui (HH:MM)

### #N タイトル

背景・状況の説明（context をそのまま）

**Q: 判断を求める問い（title から再構成）**

- A) 選択肢A
- B) 選択肢B
- C) 選択肢C

> {choice}
> {memo（あれば）}
```

既存の plan-fb 形式と互換にすることで、後から plan-negotiator が追記処理を続けられる。

追記後、チャットには:

```
PLAN.md に Q1〜QN の回答を追記しました。
```

と短く通知して、タスク継続。

### Step 5: 一時ファイル削除

```bash
rm -f "$INPUT" "$OUTPUT"
```

> デザイントークン（CSS 変数・フォントスタック）は `scripts/answer_gui.py` の `CSS` 定数を SSOT として参照する。

## context・options の書き方ルール（v2）

判断補助 UI として効くよう、Claude 側で以下を**必ず**守る。

### L1. 長文 context は箇条書きで構造化

context が 2 文以上 or 80 字を超えるなら、`-` で箇条書きにする。1 行は 60 字目安。

NG例（v1 でユーザーから FB あった形）:

> Q1で読み手概念を持たない方針に倒れたので、SPEC #2「タイトル/目的/想定読み手/量目安/記載要素」の「想定読み手」が浮く。再整理が必要。注意シグナルを残すかどうかが論点。

OK例（v2）:

```markdown
Q1 の方針: 読み手概念を持たない方向。
SPEC #2「タイトル/目的/想定読み手/量目安/記載要素」の「**想定読み手**」が浮く。

論点:
- 「想定読み手」を 4 項目に整理し直すか
- そのまま残して**注意シグナル**として運用するか
```

→ 「」内テキストは自動 chip 化される（amber pill 表示）。

### L2. 重要キーワードは **bold** 強調

「これがキモ」という単語は `**bold**` で囲む。ベタ書きの強調は使わない。

### L3. 「カギカッコ」を積極活用（3 トーン使い分け可）

固有名詞・専門用語・引用は **カギカッコで囲む** → 自動 chip 化されて scannable。
括弧の種類で色を切り替えられる:

| 記法 | 色 | 用途 |
|------|-----|------|
| `「text」` | 🟡 amber (default) | 一般引用・専門用語・literal text |
| `『text』` | 🔵 blue (info) | トピック・分類・カテゴリ名 |
| `【text】` | 🟢 green (good) | 推奨・ポジティブ・確定事項 |

例: `「文体」 を 『tone』 に統一して 【採用】 する` → 3 色 chip が並ぶ。1 カードあたり 3〜4 個までが目安（入れすぎは逆効果）。

### L3.1 prefix paragraph + bullets は空行なしでも OK

context 内で「導入文 → 箇条書き」を改行だけで繋いでも、自動でレンダリングが分割される（v2.1 で追加）:

```
5 候補:
- A: alpha
- B: beta
```

→ `<p>5 候補:</p><ul><li>A: alpha</li><li>B: beta</li></ul>` で描画。空行を挟まなくても bullet が一行にまとまる事故は起きない。

### L4. 選択肢は迷い余地があれば object 形式 + effect

シンプルな A/B/C は文字列で OK。意味の差を伝えたいときは object：

```json
"options": [
  {"value": "A: 現状維持", "recommended": true, "tone": "neutral", "effect": "コスト 0・既知の挙動"},
  {"value": "B: scripts/ 配下に統合", "tone": "replace", "effect": "整理されるが移行コスト・参照崩れ注意"},
  {"value": "C: 新フォルダ作成", "tone": "add", "effect": "スコープ膨張・将来また統合する手間"},
  {"value": "D: 削除", "tone": "remove", "effect": "壊れる可能性大"}
]
```

| フィールド | 値 | 効果 |
|---|---|---|
| `value` | 文字列（必須） | 選択肢ラベル |
| `recommended` | `true` / 省略 | ★ + amber ring（**1 問につき 1 つだけ**） |
| `tone` | `neutral` / `add`(緑) / `replace`(黄) / `remove`(赤) / `minimum`(灰) | border-left の色 |
| `effect` | 文字列 | 1 行サブテキスト（cognitive load 軽減） |

旧形式（文字列のみ）も継続サポート。

### 自動折りたたみ（context が長い場合）

answer-gui 側で context を判定して自動で `<details>` 化する：

- 箇条書き (`-`) を含む → **折りたたまない**（既に構造化されてる）
- 段落 3 つ以上 or 240 字超 → 先頭段落だけ表示・残りは `<details>`
- 先頭行が `TL;DR:` → その行を summary に、残りを details に

なので、よく構造化された context なら自然と展開表示になる。

---

## モード選択ガイド（決定木）

「もっと適切なレイアウトがあるはず」を防ぐため、**必ず以下の決定木で mode を明示指定する**こと。自動判定（mode 省略）は最後の手段。

```
1. 「現在値 vs 提案値」を比較確認したい？（current/proposed が出てくる）
     YES → mode: "diff-table" + rows 形式（ist:sync / 設定変更確認 等）
     NO  → 2 へ

2. 1 問だけで 2〜3 個の選択肢で完結？（GO/NO-GO 系・進める進めない系）
     YES → mode: "yes-no"
     NO  → 3 へ

3. PJ を横断して 4 件以上のタスク仕分け？（やる/伸ばす/捨てる の三択 + memo）
     YES → mode: "table" + 各 item に group: "PJ名" を付ける
            （PJ 列が独立し、同一 group は連続表示で見やすい）
     NO  → 4 へ

4. 各設問に背景説明（context）が 100 字以上 ある？かつ 3 問以上？
     YES → mode: "wizard"（1 問ずつ集中させる）
     NO  → 5 へ

5. それ以外（2〜10 問程度・context は短〜中）
       → mode: "card"（縦並びのカード、最もスタンダード）
```

### 各モードの代表ユースケース

| mode | 典型ユースケース | 失敗パターン（やらないこと） |
|---|---|---|
| `yes-no` | 「これで進めて OK？」「A/B どっち？」 | 3 問以上を 1 問ずつ yes-no 連発（→ wizard か card） |
| `card` | draft 壁打ち・3〜5 個の決め事・自由記述含む | 10 問以上を card で並べる（→ table か wizard） |
| `table` | タスク仕分け・4 件以上の似た形の質問 | group なしで PJ がバラバラに混在（→ group 付与） |
| `wizard` | 各 Q に長文 context・大きめ意思決定 | context が短いのに wizard（→ card で十分） |
| `diff-table` | Notion 同期前確認・設定値の上書き確認 | items 系を無理やり diff-table にする |

### 判定の優先順位

1. **`--layout` CLI フラグ**（最優先・テスト/再現用途）
2. **JSON `mode` フィールド**（このスキルから呼ぶときは**必ずこれを指定する**）
3. **kind が `rows` なら `diff-table`**
4. **auto_layout()**: 4 問以上で 75% 以上に options → `table`、それ以外 → `card`（最後の安全網）

### 入力スキーマ（object 形式）

```json
{
  "mode": "yes-no | wizard | card | table",
  "items": [
    {
      "id": "q1",
      "title": "見出し（30字以内）",
      "context": "背景・補足",
      "options": ["A: ...", "B: ..."],
      "memo_label": "補足"
    }
  ]
}
```

diff-table の場合は `items` の代わりに `rows` を使う（`diff-table` モード仕様参照）。

### options のリッチ形式（v2 で追加）

```json
"options": [
  "A: シンプル文字列でも OK",
  {"value": "B: object 形式", "recommended": true, "tone": "add", "effect": "推奨理由"}
]
```

文字列と object を混在させてもよい。

---

## 注意事項

- 直前の質問を **一切要約しない**。Claude の元の言葉をそのまま `context` に入れる
- 選択肢が長い場合（50字超）は `context` に詳細を移して `options` は短いラベルにする
- **`context` に URL を入れて OK**（Notion / Asana / Confluence など）。`[text](url)` 形式で書けばクリック可能なリンクになる（v2）。素の URL はテキスト表示
- 起動時、ブラウザは `--app=URL`（Chrome/Edge）で URL バーなしの独立ウィンドウとして前面に出る。Firefox / Safari の場合は new window 起動だが URL バーは出る
- ユーザーが Cancel した場合は、無理に処理を続けない（質問の文脈は会話に残ったまま）
- このスキルは「答えるためのツール」であって、新しい論点を Claude が増やす場ではない
- PLAN.md 追記モードでも、回答を受けて Claude 側が **次の対応案を出す**（CLI で `>>` 風に返す）

## 例: 入力→ JSON 変換

直前の Claude 発話:

```
### 認知合わせしたいポイント

1. WBS の 13 タスクを Notion に起票するか?
   - GW 前 MUST 系（見積もり最新化）は最低限起票したい
2. 既存 3 タスクの位置付け
   - 「Salesforce社交渉」(6/15) は親アイテム化候補
3. TODO.md の完了状態定義をどう書き換える?
```

変換後 JSON:

```json
[
  {
    "id": "q1",
    "title": "WBS 13 タスクの起票範囲",
    "context": "GW 前 MUST 系（見積もり最新化）は最低限起票したい",
    "options": ["A: 全 13 件起票", "B: GW 前 MUST のみ起票", "C: 既存 3 件のみで十分"],
    "memo_label": "補足"
  },
  {
    "id": "q2",
    "title": "既存 3 タスクの位置付け",
    "context": "「Salesforce社交渉」(6/15) は親アイテム化候補",
    "options": ["A: Salesforce社交渉を親に / 他 2 件を子に", "B: 親アイテム関係は設定しない", "C: 別の親を新規起票"],
    "memo_label": "補足"
  },
  {
    "id": "q3",
    "title": "TODO.md の完了状態定義書き換え",
    "context": "現状「毎週金曜に進捗確認できている」は薄い",
    "options": [],
    "memo_label": "新しい完了状態定義を記入"
  }
]
```

---

## 使い方パターン集

実戦で確認できたパターン（タスク仕分け・差分確認・group 列・PJ ソート等）は別ファイルにまとめてある:

> 📘 `${CLAUDE_PLUGIN_ROOT}/references/usage-patterns.md`

新しい用途で使う前に必ず参照すること（`title` への PJ 名混入、`group` フィールドでの PJ 列独立、items の PJ ソート、memo 解釈ルール等）。
