# draft plugin — install 手順

POH-keito の `draft` plugin（`_draft/<task>/` ベースで PLAN/SPEC/TODO/KNOWLEDGE を回す思考永続化スキル群）を、自分の Claude Code に取り込むための手順。

提供サブコマンド:

- `/draft:init` — _draft/<task>/ にテンプレ作成
- `/draft:sync` — セッション会話を draft ドキュメントに反映
- `/draft:plan-fb` — PLAN.md ベースで壁打ち
- `/draft:answer-gui` — 確認質問をブラウザで一括回答（Python stdlib のみ・依存ゼロ）

## オプション A: project scope（一番簡単・特定 repo でのみ使う）

利用したい repo の `.claude/plugins/` 配下に展開:

```bash
unzip ~/Downloads/draft.zip -d <your-repo>/.claude/plugins/
```

Claude Code セッションを再起動すれば `/draft:*` が使える。

## オプション B: user scope（cross-repo で使いたい場合）

簡易 marketplace を 1 つ作って install:

```bash
mkdir -p ~/my-plugins/.claude-plugin
unzip ~/Downloads/draft.zip -d ~/my-plugins/
cat > ~/my-plugins/.claude-plugin/marketplace.json <<'EOF'
{
  "name": "local",
  "owner": {"name": "local"},
  "plugins": [{"name": "draft", "version": "0.3.0", "source": "./draft"}]
}
EOF
claude plugin marketplace add ~/my-plugins
claude plugin install draft@local --scope user
```

## 補足

- `.claude-plugin/plugin.json` の description に `/buildin:*` への soft reference があるが、buildin plugin が無くても draft 単体で動く（外部 publish は手動で OK）。
- `/draft:answer-gui` は Python 3 stdlib のみで動作（ローカル HTTP サーバ + ブラウザ）。追加 install 不要。
