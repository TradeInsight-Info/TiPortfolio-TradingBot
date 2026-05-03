import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // All requests starting with /api will be forwarded to Flask
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        // Strip the /api prefix before forwarding to Flask
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
