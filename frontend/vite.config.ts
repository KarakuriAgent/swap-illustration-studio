import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// run.sh --dev が HOST/PORT を export するので、バックエンドのポート変更に追従する
const BACKEND =
  process.env.VITE_BACKEND_URL ??
  `http://${process.env.HOST && process.env.HOST !== '0.0.0.0' ? process.env.HOST : '127.0.0.1'}:${process.env.PORT || '2760'}`

export default defineConfig({
  plugins: [
    react(),
    // PWA: ホーム画面に追加して全画面で使える。service worker は静的アセット（ビルド成果物）だけを
    // プリキャッシュし、API（/api/*）や生成画像はキャッシュしない。
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: false,
      manifest: {
        name: 'Swap Illustration Studio',
        short_name: 'Swap Studio',
        description: 'イラストの人物を差し替える（Qwen-Image 2.1 + LoRA anime-swap）',
        lang: 'ja',
        dir: 'ltr',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'any',
        theme_color: '#121418',
        background_color: '#121418',
        icons: [
          { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/maskable-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,woff2,svg,png,webmanifest}'],
        // IBM Plex Sans JP は数百のサブセットに分かれている。全部をプリキャッシュすると重いので除外
        // （オフライン時はシステムフォントになるだけ）。index.html も常にネットワークから取る。
        globIgnores: ['**/ibm-plex-sans-jp-*.woff2', 'index.html'],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        navigateFallback: undefined,
        // API と生成画像はキャッシュしない
        runtimeCaching: [],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
      },
      devOptions: { enabled: false },
    }),
  ],
  // /assets は使わず dist/static/ に出す（バックエンドのルーティングと分けるため）
  build: { assetsDir: 'static' },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
    },
  },
})
