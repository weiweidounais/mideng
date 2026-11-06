import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({base:'/mideng/',plugins:[react()],build:{outDir:'dist-demo',rollupOptions:{input:'demo.html'}},preview:{host:'127.0.0.1',port:18432,strictPort:true}});
