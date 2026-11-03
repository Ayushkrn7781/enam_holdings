/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0E1726", surface: "#152033", raised: "#1B2940", line: "#26354F", line2: "#33446280",
        fg: "#E6ECF5", dim: "#8A9BB5", faint: "#5C6C86",
        up: "#3FB98A", info: "#5B9BF0", warn: "#E0A84B", down: "#E5675F",
        c1: "#5B9BF0", c2: "#3FB98A", c3: "#E0A84B", c4: "#A48BE8", c5: "#4FC3C9",
      },
      fontFamily: { sans: ['"Archivo Variable"', "system-ui", "sans-serif"] },
      borderRadius: { sm: "4px", DEFAULT: "6px", deck: "14px" },
    },
  },
  plugins: [],
};
