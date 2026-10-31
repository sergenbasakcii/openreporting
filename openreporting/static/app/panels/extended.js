// Additional ECharts visualizations; use query frames without synthetic values.
import { chartTheme, initChart, noData, reducedValues, reduce, minOf, maxOf, timeAxisLabel } from './common.js';
import { formatValue, resolveUnit } from '../units.js';
import { render as renderTimeSeries } from './timeseries.js';

const finite = v => typeof v === 'number' && Number.isFinite(v);
// Dates follow the dashboard time zone like the other panels ('browser' = local).
const zoneOf = tz => (!tz || tz === 'browser' ? undefined : tz === 'utc' ? 'UTC' : tz);
function dayKey(ms, tz) {
 try { return new Intl.DateTimeFormat('en-CA', { timeZone: zoneOf(tz), year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms)); }
 catch { return new Date(ms).toISOString().slice(0, 10); }
}
function stamp(ms, tz) {
 try { return new Intl.DateTimeFormat('tr-TR', { timeZone: zoneOf(tz), dateStyle: 'short', timeStyle: 'short' }).format(new Date(ms)); }
 catch { return new Date(ms).toISOString(); }
}
export const EXTRA_NAMES = {
 heatmap:'Isı haritası', histogram:'Histogram', scatter:'XY dağılım', bubble:'Balon grafik', boxplot:'Kutu grafiği',
 candlestick:'Mum grafiği', radar:'Radar', funnel:'Huni', treemap:'Ağaç haritası', sunburst:'Hiyerarşi halkası',
 sankey:'Sankey akışı', nodegraph:'Bağlantı grafiği', calendarheatmap:'Takvim ısı haritası', waterfall:'Şelale',
 polarbar:'Kutupsal çubuk', parallel:'Paralel koordinatlar', donut:'Halka grafik', rosepie:'Gül grafiği',
 stackedarea:'Yığılmış alan', stepchart:'Basamak grafiği',
};
export function extendedOption(frames, panel, tz) {
 const pointCount=frames.reduce((n,f)=>n+(f.type==='table'?f.rows.length:f.points?.length||0),0);
 if(pointCount>100000)return {message:'Bu grafik için en fazla 100.000 satır/nokta kullanın; sorguyu daraltın.'};
 const type=panel.type, table=frames.find(f=>f.type==='table'), series=frames.filter(f=>f.type==='timeseries');
 const vals=reducedValues(frames,panel).filter(i=>finite(i.value));
 const samples=series.flatMap(f=>f.points.map(p=>p[1]).filter(finite));
 const numbers=table ? table.columns.map((c,i)=>c.type==='number'?i:-1).filter(i=>i>=0):[];
 const all=samples.length?samples:(table?table.rows.flatMap(r=>numbers.map(i=>r[i]).filter(finite)):[]);
 const axis={xAxis:{type:'category',data:vals.map(i=>i.name)},yAxis:{type:'value'}};
 const items=vals.map(i=>({name:i.name,value:i.value}));
 if(['donut','rosepie','funnel','treemap','sunburst','radar','polarbar'].includes(type)) {
  if(!items.length) return null;
  if(['donut','rosepie','funnel','treemap','sunburst'].includes(type)&&items.some(i=>i.value<0))return {message:'Bu grafik negatif değerleri desteklemez; çubuk veya zaman serisi grafiği seçin.'};
  if(['donut','rosepie'].includes(type)) return {series:[{type:'pie',radius:type==='donut'?['45%','70%']:'70%',roseType:type==='rosepie'?'area':undefined,data:items.filter(i=>i.value>=0),label:{show:false}}],legend:{type:'scroll',bottom:0}};
  if(type==='funnel') return {series:[{type:'funnel',left:'10%',right:'10%',top:20,bottom:20,data:items.filter(i=>i.value>=0),label:{position:'inside'}}]};
  if(type==='treemap') return {series:[{type:'treemap',roam:false,nodeClick:false,breadcrumb:{show:false},data:items.filter(i=>i.value>=0)}]};
  if(type==='sunburst') {
   const groups=new Map(); vals.forEach(i=>{const group=Object.values(i.frame?.labels||{})[0]||'Veriler';if(!groups.has(group))groups.set(group,[]);if(i.value>=0)groups.get(group).push({name:i.name,value:i.value});});
   return {series:[{type:'sunburst',radius:[0,'85%'],data:[...groups].map(([name,children])=>({name,children})),label:{show:false}}]};
  }
  if(type==='radar') return {radar:{indicator:items.map(i=>({name:i.name})),radius:'60%'},series:[{type:'radar',data:[{value:items.map(i=>i.value),name:'Değerler'}]}]};
  return {polar:{},angleAxis:{type:'category',data:items.map(i=>i.name)},radiusAxis:{type:'value'},series:[{type:'bar',coordinateSystem:'polar',data:items.map(i=>i.value)}]};
 }
 if(['stackedarea','stepchart'].includes(type)) {
  if(!series.length)return null;
  const span=Math.max(1,maxOf(series.flatMap(f=>f.points.map(p=>p[0])),0)-minOf(series.flatMap(f=>f.points.map(p=>p[0])),0));
  return {xAxis:{type:'time',axisLabel:{hideOverlap:true,formatter:v=>timeAxisLabel(v,span,tz)}},yAxis:{type:'value'},series:series.map(f=>({name:f.name,type:'line',showSymbol:false,connectNulls:false,stack:type==='stackedarea'?'total':undefined,areaStyle:type==='stackedarea'?{}:undefined,step:type==='stepchart'?'end':undefined,data:f.points}))};
 }
 if(type==='histogram') {
  if(!all.length)return null; const lo=minOf(all),hi=maxOf(all); const n=Math.max(1,Math.min(50,Math.floor(Number(panel.options?.bins))||10)); const width=(hi-lo)/n||1, counts=Array(n).fill(0);
  all.forEach(v=>counts[Math.min(n-1,Math.floor((v-lo)/width))]++);
  return {xAxis:{type:'category',data:counts.map((_,i)=>`${(lo+i*width).toPrecision(4)}–${(lo+(i+1)*width).toPrecision(4)}`)},yAxis:{type:'value',name:'Örnek sayısı'},series:[{type:'bar',barCategoryGap:0,data:counts}]};
 }
 if(type==='boxplot') {
  const groups=series.length?series.map(f=>({name:f.name,values:f.points.map(p=>p[1]).filter(finite)})):numbers.map(i=>({name:table.columns[i].name,values:table.rows.map(r=>r[i]).filter(finite)}));
  const valid=groups.filter(g=>g.values.length); if(!valid.length)return null;
  return {xAxis:{type:'category',data:valid.map(g=>g.name)},yAxis:{type:'value'},series:[{type:'boxplot',data:valid.map(g=>{const v=g.values.sort((a,b)=>a-b);return[v[0],quantile(v,.25),quantile(v,.5),quantile(v,.75),v[v.length-1]];})}]};
 }
 if(['scatter','bubble','parallel','candlestick'].includes(type)) {
  if(!table||numbers.length<(type==='candlestick'?4:2))return {message:type==='candlestick'?'Mum grafiği için açılış, kapanış, düşük, yüksek sırasıyla dört sayısal sütun gerekir.':'En az iki sayısal sütun içeren bir tablo seçin.'};
  const used=type==='parallel'?numbers:numbers.slice(0,type==='candlestick'?4:type==='bubble'?3:2);
  const rows=table.rows.filter(r=>used.every(i=>finite(r[i]))); if(!rows.length)return null;
  if(type==='candlestick'&&rows.some(r=>r[numbers[2]]>Math.min(r[numbers[0]],r[numbers[1]])||r[numbers[3]]<Math.max(r[numbers[0]],r[numbers[1]])))return {message:'Mum verisinde düşük/açılış/kapanış/yüksek aralıklarını kontrol edin.'};
  if(type==='parallel')return {parallel:{left:55,right:30,top:35,bottom:35},parallelAxis:numbers.map((i,dim)=>({dim,name:table.columns[i].name})),series:[{type:'parallel',data:rows.map(r=>numbers.map(i=>r[i]))}]};
  if(type==='candlestick')return {xAxis:{type:'category',data:rows.map((r,i)=>String(r[table.columns.findIndex(c=>c.type!=='number')]??i+1))},yAxis:{type:'value',scale:true},series:[{type:'candlestick',data:rows.map(r=>numbers.slice(0,4).map(i=>r[i]))}]};
  return {xAxis:{type:'value',name:table.columns[numbers[0]].name},yAxis:{type:'value',name:table.columns[numbers[1]].name},series:[{type:'scatter',data:rows.map(r=>numbers.map(i=>r[i])),symbolSize:type==='bubble'?(v=>Math.max(5,Math.min(55,Math.sqrt(Math.abs(v[2]??1))*3))):8}]};
 }
 if(['sankey','nodegraph'].includes(type)) {
  if(!table)return {message:'Kaynak, hedef ve sayısal değer sütunları içeren tablo gerekir.'};
  const names=table.columns.map(c=>c.name.toLowerCase()), a=names.indexOf('source'),b=names.indexOf('target'),v=names.indexOf('value');
  if(a<0||b<0||v<0)return {message:'Tablo sütunları: source, target, value.'};
  if(table.rows.length>5000)return {message:'Bağlantı grafikleri için en fazla 5.000 satır kullanın.'};
  if(table.rows.some(r=>finite(r[v])&&r[v]<0))return {message:'Akış/bağlantı değeri negatif olamaz.'};
  const links=table.rows.filter(r=>r[a]!=null&&r[b]!=null&&finite(r[v])&&r[v]>=0).map(r=>({source:String(r[a]),target:String(r[b]),value:r[v]}));
  if(!links.length)return null; const data=[...new Set(links.flatMap(l=>[l.source,l.target]))].map(name=>({name}));
  if(type==='sankey'&&hasCycle(links))return {message:'Sankey döngü içeremez; bağlantı grafiğini seçin.'};
  return {series:[{type:type==='sankey'?'sankey':'graph',layout:type==='nodegraph'?'circular':undefined,roam:false,symbolSize:25,label:{show:true},data,links}]};
 }
 if(type==='heatmap') {
  if(!series.length)return {fallback:'timeseries'};
  const times=[...new Set(series.flatMap(f=>f.points.map(p=>p[0])))].sort((a,b)=>a-b), lookup=new Map(times.map((t,i)=>[t,i]));
  const data=series.flatMap((f,i)=>f.points.filter(p=>finite(p[1])).map(p=>[lookup.get(p[0]),i,p[1]])); if(!data.length)return null;
  return {xAxis:{type:'category',data:times.map(t=>stamp(t,tz))},yAxis:{type:'category',data:series.map(f=>f.name)},visualMap:{min:minOf(data.map(d=>d[2])),max:maxOf(data.map(d=>d[2])),calculable:true,orient:'horizontal',bottom:0},series:[{type:'heatmap',data}],grid:{bottom:70}};
 }
 if(type==='calendarheatmap') {
  const days=new Map();series.forEach(f=>f.points.filter(p=>finite(p[1])).forEach(p=>{const day=dayKey(p[0],tz);if(!days.has(day))days.set(day,[]);days.get(day).push(p[1]);}));
  const data=[...days].sort(([a],[b])=>a.localeCompare(b)).map(([day,values])=>[day,reduce(values,'mean')]);if(!data.length)return null;
  return {calendar:{range:[data[0][0],data[data.length-1][0]],cellSize:['auto',18],top:45,left:45,right:15},visualMap:{min:minOf(data.map(d=>d[1])),max:maxOf(data.map(d=>d[1])),orient:'horizontal',bottom:0},series:[{type:'heatmap',coordinateSystem:'calendar',data}]};
 }
 if(type==='waterfall') {
  if(!items.length)return null;let total=0;const steps=items.map((i,index)=>{const from=total;total+=i.value;return[index,from,total];});
  return {...axis,yAxis:{type:'value',min:Math.min(0,minOf(steps.flatMap(s=>s.slice(1)))),max:Math.max(0,maxOf(steps.flatMap(s=>s.slice(1))))},series:[{type:'custom',data:steps,renderItem:(params,api)=>{const start=api.coord([api.value(0),api.value(1)]),end=api.coord([api.value(0),api.value(2)]),width=api.size([1,0])[0]*.6;return{type:'rect',shape:{x:start[0]-width/2,y:Math.min(start[1],end[1]),width,height:Math.max(1,Math.abs(end[1]-start[1]))},style:{fill:api.value(2)>=api.value(1)?'#73bf69':'#f2495c'}};}}]};
 }
 return null;
}
function quantile(v,f){const i=(v.length-1)*f,l=Math.floor(i),h=Math.ceil(i);return v[l]+(v[h]-v[l])*(i-l);}
function hasCycle(links) {
 const edges=new Map(),degree=new Map();
 for(const link of links){if(!edges.has(link.source))edges.set(link.source,[]);edges.get(link.source).push(link.target);if(!degree.has(link.source))degree.set(link.source,0);degree.set(link.target,(degree.get(link.target)||0)+1);}
 const queue=[...degree].filter(([,n])=>n===0).map(([name])=>name);let visited=0;
 for(let i=0;i<queue.length;i++){visited++;for(const next of edges.get(queue[i])||[]){degree.set(next,degree.get(next)-1);if(degree.get(next)===0)queue.push(next);}}
 return visited!==degree.size;
}
// Value formatting (unit/decimals) shared by tooltips and value axes.
function valueFormat(frames,panel){
 const d=panel.fieldConfig?.defaults||{};const first=frames.find(f=>f.unit||f.columns?.some(c=>c.unit));
 const unit=resolveUnit(d.unit,first?.unit||first?.columns?.find(c=>c.unit)?.unit);
 return v=>(finite(v)?formatValue(v,unit,d.decimals):String(v??''));
}
export function renderExtended(container,frames,panel,ctx={}){
 const option=extendedOption(frames,panel,ctx.timezone);
 if(option?.fallback==='timeseries')return renderTimeSeries(container,frames,{...panel,type:'timeseries'},ctx);if(!option||option.message){noData(container,option?.message||'Veri yok');return{resize(){},destroy(){}};}
 const theme=chartTheme();
 const fmt=valueFormat(frames,panel);
 if(option.yAxis&&!Array.isArray(option.yAxis)&&option.yAxis.type==='value')option.yAxis={...option.yAxis,axisLabel:{...option.yAxis.axisLabel,formatter:fmt}};
 if(option.legend)option.legend={textStyle:{color:theme.text},...option.legend};
 if(option.visualMap)option.visualMap={textStyle:{color:theme.text},...option.visualMap};
 if(option.calendar)option.calendar={...option.calendar,dayLabel:{color:theme.text},monthLabel:{color:theme.text},yearLabel:{color:theme.text}};
 option.series=option.series.map(s=>({...s,label:{...s.label,color:theme.text}}));
 const box=document.createElement('div');box.className='viz-chart';box.style.height='100%';container.replaceChildren(box);const chart=initChart(box);
 chart.setOption({animation:false,color:['#5794f2','#73bf69','#ff9830','#b877d9','#f2495c'],textStyle:{color:theme.text},grid:{left:50,right:25,top:30,bottom:50,containLabel:true},tooltip:{trigger:'item',confine:true,renderMode:'richText',backgroundColor:theme.tooltipBg,borderColor:theme.border,textStyle:{color:theme.text},valueFormatter:fmt},...option},true);
 return{chart,resize(){chart.resize();},destroy(){chart.dispose();},png(){return chart.getDataURL({type:'png',pixelRatio:2,backgroundColor:theme.bg});}};
}
