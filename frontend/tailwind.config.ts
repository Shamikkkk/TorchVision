import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Obsidian Ember palette
        ember: {
          50: '#fff7ed',
          100: '#ffedd5',
          200: '#fed7aa',
          300: '#fdba74',
          400: '#ff9a5a',  // primary accent
          500: '#ff7a2a',  // main brand orange
          600: '#ea5a0c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
          950: '#431407',
        },
        pyro: {
          bg: '#0f0b08',
          surface: '#1a1510',
          border: '#2a1a10',
          'border-subtle': 'rgba(255, 120, 40, 0.08)',
          'border-accent': 'rgba(255, 120, 40, 0.15)',
          text: '#e8d8b8',
          'text-dim': '#8a7c68',
          'text-muted': '#6a5e50',
          'text-faint': '#5a5048',
          cream: '#f5ecd4',
          taunt: '#ffb080',
        },
        board: {
          light: '#e8d4a8',
          dark: '#8b6240',
          'last-move': 'rgba(255, 170, 60, 0.45)',
          check: 'rgba(220, 60, 40, 0.65)',
        },
      },
      fontFamily: {
        'display': ['"Instrument Serif"', 'Georgia', 'serif'],
        'sans': ['Inter', 'system-ui', 'sans-serif'],
        'mono': ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      animation: {
        'pyro-flicker': 'pyroFlicker 3s ease-in-out infinite',
        'pyro-pulse': 'pyroPulse 1.2s ease-in-out infinite',
        'pyro-taunt-in': 'pyroTauntIn 400ms ease-out',
        'pyro-fade-up': 'pyroFadeUp 700ms ease-out',
      },
      keyframes: {
        pyroFlicker: {
          '0%, 100%': { opacity: '1' },
          '48%': { opacity: '0.92' },
          '50%': { opacity: '0.78' },
          '52%': { opacity: '0.95' },
        },
        pyroPulse: {
          '0%, 100%': { opacity: '0.7', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.05)' },
        },
        pyroTauntIn: {
          '0%': { opacity: '0', transform: 'translateX(-8px) scale(0.95)' },
          '100%': { opacity: '1', transform: 'translateX(0) scale(1)' },
        },
        pyroFadeUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
