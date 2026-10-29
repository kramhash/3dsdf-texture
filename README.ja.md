# 3dsdf-texture

Blender 5.2 のメッシュを 3D 符号付き距離場テクスチャに焼く Extension です。[frapx](https://github.com/kramhash/frapx) の SDF volume の素材を作るために書いたもので、three.js と Godot 4 からも読めます。

正は英語の [README.md](README.md) と [docs/format.md](docs/format.md) です。ここには入口だけを書きます。

## 入れ方

[Releases](https://github.com/kramhash/3dsdf-texture/releases) から `sdf_texture-<version>.zip` を落とし、Blender にドラッグ＆ドロップします（または Preferences → Get Extensions → Install from Disk）。Blender 5.2 以降が要ります。更新は手動で、新しい zip を上から入れます。

## 使い方

3D ビューの N パネル「SDF」で、解像度、形式、出力先を選んで「Bake SDF Texture」を押します。

- パネルには選択中のオブジェクトの三角形数が出ます。5 万を超えるものは焼くのに時間がかかるので警告します
- 焼いている間はボタンが進捗バーと残り時間に替わります。その間も操作でき、Esc で中断できます
- 終わると結果がパネルに残り、「Open Output Folder」で出力先を開けます
- 出力先の既定 `//sdf/` は .blend からの相対パスなので、先に保存してください

CLI はリポジトリを clone して `scripts/bake_cli.py` を使います。

## 出力

- `<name>.sdf.ktx2`: Web 向けです。3D KTX2 で、メタは中に入ります。既定は非圧縮で、「Zstd Compression」（CLI は `--zstd`）で zstd 圧縮にできます。効くのは主に r8 で、読み手に zstd の展開器が要ります
- `<name>.sdf.json` と、`.exr` または `.png` のアトラス: Godot 向けです

0.x の間は形式が変わることがあります（[CHANGELOG.md](CHANGELOG.md)）。
