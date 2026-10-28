# viewer-three

## フレームワーク
- Vite + React 19 + TypeScript + Motion + Tailwind CSS 4
- ビルド: `tsc -b && vite build`（型チェックを含む）

## コマンド
- `pnpm dev` - 開発サーバー（localhost:5173）
- `pnpm build` - プロダクションビルド（型チェック含む）
- `pnpm lint` - ESLint 実行

## アニメーション
- Motion を使用: `import { motion, AnimatePresence } from "motion/react"`
- exit アニメーションが必要な場合のみ `AnimatePresence` でラップ
- 複雑なスクロールトリガーが必要な場合は GSAP を追加

## Three.js（使用する場合）
- `pnpm add three @react-three/fiber @react-three/drei @types/three`
- R3F（@react-three/fiber）+ Drei を使う
- WebGLRenderer は `renderer.dispose()` で必ずリソース解放

## スタイル
- `src/index.css` の `:root {}` にデザイントークンを定義
- `@theme {}` で Tailwind ユーティリティクラス化
- Figma MCP → `get_design_context` → CSS 変数 → `@theme` の順で反映
- Figma URL からの実装は `figma-to-code` skill を使用（dev ポート: 5173）

## コンポーネント規約
- 関数コンポーネントのみ
- カスタムフックは `src/hooks/` に配置（`use` プレフィックス）
- パスエイリアス `@/` = `src/`
