const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const web = path.join(root, 'spug_web');
const modules = path.join(web, 'node_modules');
const out = path.join(__dirname, 'docker-metrics-visual');
fs.mkdirSync(out, {recursive: true});
fs.writeFileSync(path.join(out, 'libs.js'), `
export const t = x => x;
export const http = {get: async (url, {params}) => {
 const now = Date.now()/1000;
 return {host_id: params.id, sampled_at: now, server_time: now,
 history: Array.from({length: 40}, (_, i) => ({ts: now-(39-i)*5, cpu: i === 20 ? null : Math.round(38+20*Math.sin(i/4)),
 memory: Math.round(52+5*Math.sin(i/8)), gpu_status: params.id===2?'absent':'available',
 gpu: params.id===2?[]:[{id:0,value:Math.round(60+25*Math.sin(i/5))}, {id:1,value:Math.round(30+15*Math.cos(i/4))}]}))};
}};
`);
fs.writeFileSync(path.join(out, 'entry.js'), `
import React from 'react'; import ReactDOM from 'react-dom';
import HostMetrics from '${path.join(web, 'src/pages/docker/HostMetrics.js')}';
function App() {const [id,setId]=React.useState(1); return <main style={{padding:20,background:'#f5f7fa',fontFamily:'system-ui'}}>
<h2>Docker 概览 · 隔离模拟数据</h2><button onClick={()=>setId(id===1?2:1)}>切换 GPU / 无 GPU 主机</button>
<HostMetrics hostId={id}/><div style={{display:'flex',gap:16,flexWrap:'wrap'}}>{['运行中容器 12','暂停容器 0','停止容器 1','容器总数 13'].map(x=><div key={x} style={{padding:24,background:'white',flex:1}}>{x}</div>)}</div>
</main>}; ReactDOM.render(<App/>,document.getElementById('root'));
`);
fs.writeFileSync(path.join(out, 'index.html'), '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script src="bundle.js"></script>');
const webpack = require(path.join(modules, 'webpack'));
webpack({mode:'development',entry:path.join(out,'entry.js'),output:{path:out,filename:'bundle.js'},
 resolve:{modules:[modules],alias:{libs:path.join(out,'libs.js')}},
 resolveLoader:{modules:[modules,path.join(modules,'react-scripts/node_modules')]},
 module:{rules:[{test:/\.js$/,exclude:/node_modules/,use:{loader:'babel-loader',options:{presets:[path.join(modules,'@babel/preset-react')],plugins:[path.join(modules,'babel-preset-react-app/node_modules/@babel/plugin-proposal-optional-chaining'),path.join(modules,'babel-preset-react-app/node_modules/@babel/plugin-proposal-nullish-coalescing-operator')]}}},
 {test:/\.less$/,use:['style-loader',{loader:'css-loader',options:{modules:true}},'less-loader']}]}},(err,stats)=>{if(err||stats.hasErrors()){console.error(err||stats.toString());process.exitCode=1;}else console.log('Visual harness compiled');});
