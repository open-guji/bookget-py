import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import dts from 'vite-plugin-dts';
import { resolve } from 'path';

export default defineConfig(({ mode }) => {
  // Library mode: build as npm package
  if (mode === 'lib') {
    return {
      plugins: [
        react(),
        dts({ include: ['src/'], outDir: 'dist', rollupTypes: true }),
      ],
      build: {
        lib: {
          entry: resolve(__dirname, 'src/index.ts'),
          name: 'BookgetUI',
          formats: ['es', 'cjs'],
          fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
        },
        rollupOptions: {
          external: ['react', 'react-dom', 'react/jsx-runtime'],
          output: {
            globals: {
              react: 'React',
              'react-dom': 'ReactDOM',
            },
          },
        },
        outDir: 'dist',
        cssCodeSplit: false,
      },
    };
  }

  // App mode: build standalone web application
  return {
    plugins: [react()],
    root: resolve(__dirname, 'app'),
    build: {
      outDir: resolve(__dirname, 'dist-app'),
      emptyOutDir: true,
    },
    server: {
      proxy: {
        '/api': {
          target: 'http://localhost:8765',
          changeOrigin: true,
        },
      },
    },
  };
});
