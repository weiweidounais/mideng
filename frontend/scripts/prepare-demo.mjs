import {readFile,writeFile,copyFile,readdir} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'../dist-demo');
const html=await readFile(path.join(root,'demo.html'),'utf8');
if(!html.includes("connect-src 'none'")||!html.includes('/mideng/assets/'))throw new Error('Public demo boundary or asset base is missing');
await copyFile(path.join(root,'demo.html'),path.join(root,'index.html'));
await writeFile(path.join(root,'.nojekyll'),'');
async function files(dir){return (await Promise.all((await readdir(dir,{withFileTypes:true})).map(e=>e.isDirectory()?files(path.join(dir,e.name)):[path.join(dir,e.name)]))).flat();}
for(const file of await files(root)){
 if(/\.(?:db|sqlite|pem|key|zip|json|env)$/.test(file))throw new Error('Unexpected data artifact in demo: '+path.basename(file));
 if(/\.(?:js|html|css)$/.test(file)){
  const content=await readFile(file,'utf8');
  if(/127\.0\.0\.1:18410|127\.0\.0\.1:18430|bootstrap-passwords|zhixu_session|mideng_pilot_session/.test(content))throw new Error('Private runtime reference in demo artifact');
 }
}
console.log('Public demo artifact: static files only; CSP blocks all backend connections.');
