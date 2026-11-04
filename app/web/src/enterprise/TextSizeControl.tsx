import {useEffect,useState} from "react";

export const READING_KEY="agentsplc.reading-percent.v1";
const clamp=(value:number)=>Number.isFinite(value)?Math.min(160,Math.max(90,Math.round(value/10)*10)):100;
export default function TextSizeControl(){
 const [percent,setPercent]=useState(()=>{try{return clamp(Number(localStorage.getItem(READING_KEY)||100));}catch{return 100;}});
 useEffect(()=>{document.documentElement.style.setProperty("--reading-scale",String(percent/100));try{localStorage.setItem(READING_KEY,String(percent));}catch{}},[percent]);
 useEffect(()=>{const sync=(event:StorageEvent)=>{if(event.key===READING_KEY)setPercent(clamp(Number(event.newValue||100)));};window.addEventListener("storage",sync);return()=>window.removeEventListener("storage",sync);},[]);
 return <div className="ep-text-size" role="group" aria-label="字体大小"><span>字体</span><button type="button" aria-label="缩小字体" disabled={percent===90} onClick={()=>setPercent(v=>clamp(v-10))}>A−</button><output aria-live="polite" aria-label="字体比例">{percent}%</output><button type="button" aria-label="放大字体" disabled={percent===160} onClick={()=>setPercent(v=>clamp(v+10))}>A＋</button><button type="button" aria-label="恢复默认字体" onClick={()=>setPercent(100)}>默认</button></div>;
}
