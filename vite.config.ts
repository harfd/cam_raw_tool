import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  envPrefix: ['VITE_'],
  define: { 'import.meta.env.VITE_API_TOKEN': JSON.stringify(process.env.RAW_STUDIO_TOKEN || '') },
  server: { proxy: { '/api': 'http://127.0.0.1:18763' }, watch: { ignored: ['**/work/**', '**/.venv/**', '**/.tools/**', '**/build/**', '**/src-tauri/target/**', '**/dist/**', '**/release/**', '**/*.log', '**/*.NEF', '**/*.nef', '**/*.xmp', '**/*.acr'] } },
  clearScreen: false,
  build: { outDir: 'dist/ui' },
});
