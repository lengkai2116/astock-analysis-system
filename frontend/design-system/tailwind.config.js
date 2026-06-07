/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      spacing: {
        4.5: '4px',
        8: '8px',
        12: '12px',
        16: '16px',
        24: '24px',
        32: '32px',
        40: '40px',
        48: '48px'
      },
      fontSize: {
        'token-xs': ['12px', { lineHeight: '1.5' }],
        'token-sm': ['14px', { lineHeight: '1.5' }],
        'token-base': ['16px', { lineHeight: '1.6' }],
        'token-lg': ['20px', { lineHeight: '1.5' }],
        'token-xl': ['24px', { lineHeight: '1.4' }],
        'token-2xl': ['32px', { lineHeight: '1.3' }]
      },
      borderRadius: {
        'token-sm': '6px',
        'token-md': '10px',
        'token-lg': '12px',
        'token-full': '9999px'
      },
      boxShadow: {
        'token-default': '0 1px 2px 0 rgb(0 0 0 / 0.05)',
        'token-hover': '0 4px 6px -1px rgb(0 0 0 / 0.08)',
        'token-dark-default': '0 1px 2px 0 rgb(0 0 0 / 0.3)',
        'token-dark-hover': '0 4px 6px -1px rgb(0 0 0 / 0.4)'
      },
      height: {
        'btn': '40px',
        'input': '40px'
      },
      width: {
        'icon-sm': '16px',
        'icon-md': '20px'
      },
      maxWidth: {
        'page': '1200px'
      },
      padding: {
        'page-x': '24px'
      },
      gap: {
        'card': '16px'
      },
      borderWidth: {
        'token': '1px'
      }
    }
  },
  plugins: []
}
