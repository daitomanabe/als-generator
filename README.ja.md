# als-generator

Python の標準ライブラリだけで、Ableton Live のセット(`.als`)を生成します。

`.als` は gzip で圧縮した XML です。このリポジトリには、Live 12 で開けるセットを書くための検証済みのコードと覚え書きが入っています。Arrangement にクリップを置いたオーディオトラック、MIDI クリップ、リターン、Live 自身のプリセットから作る標準デバイスのチェーン、サイドチェイン、ロケーター、テンポ、13/16 のような変則拍子、そして構造の検査まで扱います。

AI エージェントのスキル(`SKILL.md` と `references/`)としても書かれているので、Claude Code や Codex などから使えます。

Ableton および Ableton Live は Ableton AG の商標です。このプロジェクトは Ableton とは無関係で、Ableton の承認も受けていません。Ableton のファイルは含みません。デバイスのプリセットは、ビルドのときにお使いの Live から読み込みます。

## なぜ必要か

2026-11-20 の比較です。同じモデル(Claude Sonnet)が、このスキルなしで記憶だけから `.als` を書くと、デバイスなしの簡単なセットでも Live 12.4.16 が 2 回落ち、デバイスありのセットは「corrupt」として開けませんでした。このスキルを使って生成した 3 つのセット(オーディオトラック 12〜16 本、Arrangement のクリップは最大 1,341 個、4/4 と 13/16)は、1 回目で開けました。

記憶だけでは、骨組みしか合いません。モデルは Live 11 の `MasterTrack` を書き、Live 12 の要素の種類も半分ほどしか書けませんでした。肝心な細部(ID の決まり、一覧の要素の Id、宙に浮いた参照、ワープマーカー、サンプルの CRC)を記録しているのが、このリポジトリです。

## クイックスタート

必要なもの: Python 3 と、インストール済みの Ableton Live 12(標準のプリセットをその Core Library から読みます)。スクリプトが Live を起動することはありません。

```bash
git clone https://github.com/daitomanabe/als-generator
cd als-generator
python3 examples/make_example.py
```

短い WAV を 5 つ合成し、スコアを 2 つ書き、`examples/out/Example Project/` に `Example 4-4.als` と `Example 13-16.als` を作って、両方に検査をかけます。Live で開く前に、いまのセットを保存してください。開くのはご自身で行います。

Core Library の探し方: 環境変数 `ABLETON_CORE_LIBRARY` があればそれを使い、なければ `/Applications/Ableton Live 12*.app/Contents/App-Resources/Core Library` を探します。Suite、Standard、Intro、Lite のどれでも探します。ここで使うプリセットは Suite のインストールで確かめました。エディションによってはプリセットが一部入っていないことがあり、その場合はビルドが「preset not found」のエラーで止まります。

## score.json

`scripts/build_als.py` は、スコアからセットを作ります。

```json
{
  "title": "My Set", "tempo": 120.0, "bars": 8, "time_signature": [4, 4],
  "samples_dir": "path/to/Project/Samples/Imported",
  "locators": [{"beat": 0.0, "name": "Intro"}],
  "tracks": [
    {"name": "Kick", "role": "kick", "volume_db": -3.0, "pan": 0.0,
     "send_a_db": -12.0, "send_b_db": -70.0, "send_c_db": -70.0,
     "clips": [{"sample": "kick.wav", "beat": 0.0, "length_beats": 16, "gain_db": 0.0}]}
  ]
}
```

```bash
python3 scripts/build_als.py score.json --out "Project/My Set.als"
python3 scripts/check_als.py "Project/My Set.als" score.json
```

- 拍は 4 分音符の数です。13/16 の 1 小節は 3.25 拍です。`samples_dir` は、リポジトリのルートからの相対パスか、絶対パスで指定します。
- `role`(kick、snare、hats、sub、pad、strike、bass など)ごとに、色・ハイパスの周波数・サイドチェインの設定が `build_als.py` の先頭の表から決まります。これらは一例です。曲に合わせて直して使い、`check_als.py` も合わせて直してください。
- 出力は、Arrangement のクリップ(ファイル本来の速さで Beats ワープ、ループなし、5 ms のフェードアウト)、3 本のリターン(リバーブ、ディレイ、サチュレーターと Redux)、マスターのチェーン(EQ Eight、Bass Mono、Limiter)です。

## MIDI だけのセット

`references/als_generator.py` で、MIDI トラックとクリップのセットを作れます。

```python
from als_generator import ALSGenerator

gen = ALSGenerator(tempo=120)
t = gen.add_midi_track("Bass", color=7)
gen.add_clip(t, clip_start=0, clip_length=4, clip_name="Loop", notes=[(36, 0.0, 0.5, 100), (38, 2.0, 0.25, 110)])
gen.save("output.als")
```

## 必須の検査(Hard QA gates)

次の検査に通らないセットは納品しません(詳細は `references/qa-gates.md`。`scripts/check_als.py` が実装しています)。

1. gzip が壊れていないこと。2. XML が読めること。
3. `NextPointeeId` が、ファイル内のどの Id よりも大きいこと。
4. Pointee の名前空間(Pointee、AutomationTarget、ModulationTarget、ControllerTargets)の Id が重複しないこと。
5. 一覧(Devices、Tracks、Events、WarpMarkers など)の要素が、すべて `Id` を持つこと。
6. 宙に浮いた参照がないこと。GrooveId、PointeeId、経路の宛先が、すべてセットの中で見つかること。

検査に通ることは、Live での読み込みの確認ではありません。

## エージェントのスキルとして使う

リポジトリのいちばん上がスキルのフォルダなので、clone するだけで入ります。

```bash
git clone https://github.com/daitomanabe/als-generator ~/.claude/skills/als-generator
```

Codex など別のエージェントでは、そのエージェントが読むスキルのフォルダに clone してください。`SKILL.md` は短く、詳細は `references/` を案内しています。

## 検証した環境と限界

- 環境: macOS、Ableton Live 12.4.16 Suite、Python 3。
- `scripts/build_als.py` で作ったセットは、Live 12.4.16 で開けました。確かめたのは構造が読み込めることです。音と、いくつかの値の意味(リバーブの wet、ディレイの同期、サイドチェインの効き、13/16 の表示のされ方)は、Live の画面で確かめていません。そうした項目は `references/` に「not verified(未確認)」と印が付いています。`examples/make_example.py` が作る 2 つの例のセットは、検査には通りますが、それ自体はまだ Live で開いていません。
- Live で開くのは、人が行う手順です。壊れたセットは「corrupt」のダイアログが出るだけでなく、Live ごと落ちることがあります。生成したセットを開く前に、いまのセットを保存してください。
- プラグイン(VST/AU)のデバイスは、手で保存した型が必要です。`references/plugin-devices.md` を見てください。

## ライセンス

MIT です。`LICENSE` を見てください。Ableton および Ableton Live は Ableton AG の商標です。このプロジェクトは Ableton とは無関係で、Ableton の承認も受けていません。Ableton のファイルは含みません。デバイスのプリセットは、ビルドのときにお使いの Live から読み込みます。
