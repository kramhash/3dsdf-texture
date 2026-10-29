# viewer-three

3dsdf-texture が書き出した `.sdf.ktx2` を three.js で確かめるビューア。SDF を `Data3DTexture` に載せて sphere tracing し、同じ形の glb と重ねて比べる。

## 構成
- Vite + React 19 + TypeScript + @react-three/fiber / drei + Tailwind CSS 4
- `src/lib/sdf.ts`: KTX2 の読み手（three 同梱の `ktx-parse`）。形式の正は `../docs/format.md` で、このファイルはそれに従う。形式を変えるときは format.md を先に直す
- `src/hooks/useSdf.ts`: 読み込みと破棄。zstd（scheme 2）は fzstd の展開関数を `loadSdf(url, { zstd })` に渡す
- `src/components/SdfVolume.tsx` / `Scene.tsx`: レイマーチと glb の重ね表示

## URL パラメータ
`?sdf=/sdf/Suzanne.r16f.sdf.ktx2&glb=/sdf/suzanne.glb&mode=sdf|mesh|both`

## サンプル
- `public/sdf/` に置く。コミットするのは r16f だけで、r8 / r32f / r8-zstd は `../samples/build.sh` で作る

## コマンド
- `pnpm dev` - 開発サーバー
- `pnpm build` - 型チェック込みのビルド（`tsc -b && vite build`）
- `pnpm lint` - ESLint

## 規約
- 関数コンポーネントのみ。フックは `src/hooks/`（`use` プレフィックス）。パスエイリアス `@/` = `src/`
- テクスチャとマテリアルは effect の後始末で `dispose()` する
