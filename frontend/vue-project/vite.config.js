import { defineConfig, loadEnv } from 'vite'
import vue2 from '@vitejs/plugin-vue2'
import vue2Jsx from '@vitejs/plugin-vue2-jsx'
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
        { find: /^store$/, replacement: 'store/dist/store.modern.js' },
        { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) },
        { find: '@$', replacement: fileURLToPath(new URL('./src', import.meta.url)) }
      ],
      extensions: ['.mjs', '.js', '.mts', '.ts', '.jsx', '.tsx', '.json', '.vue']
    },
    define: {
      'process.env.VUE_APP_API_BASE_URL': JSON.stringify(env.VITE_API_BASE_URL || 'http://localhost:5001'),
      'process.env.VUE_APP_PREVIEW': JSON.stringify(env.VITE_PREVIEW || '')
    },
    css: {
      preprocessorOptions: {
        less: {
          javascriptEnabled: true,
          modifyVars: {
            'border-radius-base': '4px'
          }
        }
      }
    },
    plugins: [
      vue2(),
      vue2Jsx(),
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
            'ant-design-vue': ['ant-design-vue'],
            'klinecharts': ['klinecharts'],
            'codemirror': ['codemirror']
          }
        }
      }
    }
  }
})
