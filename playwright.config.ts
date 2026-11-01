import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/ui', timeout: 90000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1050 }, headless: true },
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: false, timeout: 60000, env: { RAW_STUDIO_DATA_DIR: 'E:/Prj/camera_raw_tool/work/ui-test-data' } },
  outputDir: './work/playwright-results',
});
