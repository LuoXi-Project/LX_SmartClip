/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#3b82f6',
        secondary: '#8b5cf6',
      },
      keyframes: {
        blob: {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '33%': { transform: 'translate(28px, -36px) scale(1.06)' },
          '66%': { transform: 'translate(-22px, 18px) scale(0.94)' },
        },
        'about-in': {
          '0%': { opacity: '0', transform: 'translateY(14px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'home-marquee': {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
      },
      animation: {
        blob: 'blob 9s ease-in-out infinite',
        'blob-slow': 'blob 14s ease-in-out infinite',
        'blob-slower': 'blob 20s ease-in-out infinite',
        'about-in': 'about-in 0.65s ease-out forwards',
        'home-marquee': 'home-marquee 28s linear infinite',
      },
    },
  },
  plugins: [],
}
