# Work Toolkit

Claude Codeで業務に使える道具を配布しています。

## draft：作業のセーブデータを残す

Claude Codeの入力欄で次を1行ずつ実行します。

```text
/plugin marketplace add POH-keito/work-toolkit
/plugin install draft@work-toolkit
```

作業の始めに `/draft:init` で計画とチェックリストを作り、区切りで `/draft:sync` を使って決定事項と残りの作業を反映します。計画の相談には `/draft:plan-fb`、複数の質問への一括回答には `/draft:answer-gui` を使えます。回答画面を使う場合はPython 3が必要です。
