/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#e5ddc8', // page background (beige)
          900: '#f3ecd8', // card / panel surface
          800: '#ede5d0', // hover / subtle fill
          700: '#d4c8ac', // border
          600: '#bfb28e', // stronger border / disabled
          500: '#9e906d', // muted icon
          400: '#6f6448', // muted text
          300: '#4a4230', // secondary text
          200: '#332d1f', // body text
          100: '#1f1b10', // strong text / headings
        },
        accent: {
          DEFAULT: '#6b4fe3',
          hover: '#5a3ed2',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(60, 40, 10, 0.04), 0 1px 3px rgba(60, 40, 10, 0.06)',
        'panel-lg': '0 2px 4px rgba(60, 40, 10, 0.05), 0 8px 24px -6px rgba(60, 40, 10, 0.12)',
      },
    },
  },
  plugins: [],
}
