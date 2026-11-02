import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({mode})=>{
 const prototype=mode==='prototype';
 const blockBackend=(server:any)=>{server.middlewares.use('/api',(_request:any,response:any)=>{
  response.statusCode=503;response.setHeader('Content-Type','application/json; charset=utf-8');
  response.end(JSON.stringify({detail:'本地原型不连接真实后端；此请求已阻止。'}));
 });};
 return {plugins:[react(),...(prototype?[{name:'local-prototype-boundary',configureServer:blockBackend,configurePreviewServer:blockBackend}]:[])],
  server:{port:5173,strictPort:true,...(!prototype?{proxy:{'/api':{target:'http://127.0.0.1:8000',changeOrigin:false}}}:{})},
  build:{chunkSizeWarningLimit:1300}};
});
