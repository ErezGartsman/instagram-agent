// Tailwind v4 runs as a PostCSS plugin (Vite applies PostCSS automatically).
// Using the PostCSS integration — rather than @tailwindcss/vite — keeps Tailwind
// decoupled from the Vite major version (this repo is on Vite 8).
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
}
