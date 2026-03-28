/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#f0f3f9",
          100: "#d9e0f0",
          200: "#b3c1e0",
          300: "#8da2d1",
          400: "#6783c1",
          500: "#4164b2",
          600: "#34508e",
          700: "#273c6b",
          800: "#1a2847",
          900: "#0d1424",
          950: "#070a12",
        },
        gold: {
          50: "#fdf9ef",
          100: "#faf0d0",
          200: "#f5e0a0",
          300: "#f0d070",
          400: "#ebc040",
          500: "#d4a520",
          600: "#b08618",
          700: "#8c6712",
          800: "#68480c",
          900: "#442906",
        },
      },
      fontFamily: {
        display: ["Playfair Display", "Georgia", "serif"],
        body: ["DM Sans", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
