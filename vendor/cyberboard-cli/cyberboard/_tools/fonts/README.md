# Bundled pixel fonts

## tom-thumb.bdf

5px-tall pixel font used by `cb_anim.py` の `text_scroll` 効果(40×5 ディスプレイ用)。

- **正体**: 内部名 `Fixed4x6`(FOUNDRY `Raccoon`)。4×6 箱・3×5〜5px 字面の極小等幅。
  大文字は 5px フルに立ち、小文字+デセンダ(g/j/p/q/y)も 5px 内に圧縮されてクリップしない
  = **5px ディスプレイのテキストに最適**。
- **取得元**: u8g2 リポジトリのミラー
  `https://raw.githubusercontent.com/olikraus/u8g2/master/tools/font/bdf/tom-thumb.bdf`
- **ライセンス**: MIT(BDF の `COPYRIGHT` フィールド参照)。再配布可。**自作フォントではない**
  (advisor 指針「グリフは手で作らず既存の設計フォントを使う」に従い vendoring)。

40×5 での legibility は実描画で確認済み(`HELLO`/小文字/数字/デセンダ、`90` 続17)。
