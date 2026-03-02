# Translation Streamer

これは日本語の音声をリアルタイムで英語に翻訳し、vMixのテキスト入力に送信するためのスクリプトです。

## 主な機能

- マイク音声をGoogle Cloud Speech-to-Textで文字起こし
- 誤認識修正用の補正辞書を適用
- Google Cloud Translation APIで英語に翻訳
- vMix APIにテキストを送信
- 生成した英語テキストをGoogle Cloud Text-to-Speechで読み上げ
- ログファイルに翻訳内容を記録

## ファイル構成

- `index.py`：メインスクリプト
- `requirements.txt`：必要なPythonライブラリ
- `comworks-stream1-dae0ee0dd58b.json`：Google Cloudの認証ファイル *別途入手が必要です
- `Translation.vmix`：vMixプロジェクトファイル（設定用）
- `README.md`：プロジェクト説明

## 使用方法

1. Google CloudのサービスアカウントJSONをワークスペース直下に配置し、`JSON_NAME`を合わせる。
2. 仮想環境を作成し、`requirements.txt`をインストール。
3. vMixを起動しAPIを有効化。
4. https://note.com/opendemjapan/n/neebe80da133d を参考にシステム＞サウンドの入力をVB-Audio Virtual CableのCable Outputに設定。
4. `python index.py` でスクリプトを実行。

## 注意点

- vMixのURLや入力名は必要に応じて変更してください。
- 必要なGoogle Cloud APIが有効になっていることを確認してください。

---

（このREADMEは自動生成されました）