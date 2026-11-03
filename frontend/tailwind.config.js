/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0E1726", surface: "#152033", raised: "#1B2940", line: "#26354F",
        fg: "#E6ECF5", dim: "#8A9BB5", faint: "#5C6C86",
        up: "#3FB98A", info: "#5B9BF0", warn: "#E0A84B", down: "#E5675F",
        "c-category": "#5B9BF0", "c-financial": "#3FB98A", "c-deviation": "#E0A84B",
        "c-relevance": "#A48BE8", "c-novelty": "#4FC3C9",
      },
      fontFamily: { sans: ['"Archivo Variable"', "system-ui", "sans-serif"] },
      borderRadius: { DEFAULT: "6px", md: "6px", lg: "6px", sheet: "14px" },
    },
  },
  plugins: [],
};
