import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: false,   // 不生成 .d.ts，避免触发 HMR 刷新
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: false,   // 同上
    }),
  ],
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    port: 80,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    watch: {
      // 忽略后端目录，防止后端文件变化触发前端刷新
      ignored: ['**/backend/**', '**/venv/**', '**/*.py', '**/*.log'],
    },
  },
})
