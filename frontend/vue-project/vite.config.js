import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import svgLoader from 'vite-svg-loader'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    base: './',
    resolve: {
      alias: [
        { find: /^~(.+)/, replacement: '$1' },
        { find: /^moment$/, replacement: fileURLToPath(new URL('./src/shims/moment.js', import.meta.url)) },
        { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) }
      ],
      extensions: ['.mjs', '.js', '.mts', '.ts', '.jsx', '.tsx', '.json', '.vue']
    },
    css: {
      preprocessorOptions: {
        less: {
          javascriptEnabled: true
        }
      }
    },
    plugins: [
      vue(),
      vueJsx(),
      svgLoader({ defaultImport: 'url' })
    ],
    server: {
      port: 9000,
      proxy: {
        '/api': {
          target: env.VITE_DEV_PROXY_TARGET || 'http://localhost:5001',
          ws: true,
          changeOrigin: true,
          timeout: 600000,
          proxyTimeout: 600000
        }
      }
    },
    build: {
      target: 'es2020',
      sourcemap: false,
      chunkSizeWarningLimit: 1500,
      commonjsOptions: {
        transformMixedEsModules: true
      },
      rollupOptions: {
        output: {
          manualChunks: {
            'vendor-vue': ['vue', 'vue-router', 'pinia'],
            'vendor-antd': ['ant-design-vue', '@ant-design/icons-vue'],
            'vendor-echarts': ['echarts'],
            'vendor-kline': ['klinecharts'],
            'data-services': [
              './src/services/chartService.js',
              './src/services/screenerService.js',
              './src/services/aiAnalysisService.js',
              './src/services/dataService.js',
              './src/services/factorService.js',
            ],
            'analysis-views': [
              './src/views/screener/index.vue',
              './src/views/backtest/index.vue',
              './src/views/ai-analysis/index.vue',
              './src/views/indicator-ide/index.vue',
            ],
          }
        }
      }
    }
  }
})
