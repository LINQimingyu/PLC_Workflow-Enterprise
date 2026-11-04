(()=>{'use strict';
 const key='agentsplc.reading-percent.v1';
 const clamp=v=>Number.isFinite(v)?Math.min(160,Math.max(90,Math.round(v/10)*10)):100;
 let percent=100;
 try{percent=clamp(Number(localStorage.getItem(key)||100));}catch{}
 const embedded=parent!==window;
 document.documentElement.classList.toggle('embedded',embedded);
 function reportHeight(){if(embedded)parent.postMessage({type:'agentsplc-guide-height',height:Math.ceil(document.body.getBoundingClientRect().height)},'*');}
 function apply(next,persist=true){percent=clamp(next);document.documentElement.style.setProperty('--reading-scale',String(percent/100));
  document.querySelectorAll('[data-font-output]').forEach(e=>e.textContent=percent+'%');
  document.querySelectorAll('[data-font-action=decrease]').forEach(e=>e.disabled=percent===90);
  document.querySelectorAll('[data-font-action=increase]').forEach(e=>e.disabled=percent===160);
  if(persist&&!embedded)try{localStorage.setItem(key,String(percent));}catch{}
  document.querySelectorAll('iframe.guide-frame').forEach(f=>f.contentWindow?.postMessage({type:'agentsplc-reading-size',percent},'*'));
  requestAnimationFrame(reportHeight);
 }
 document.querySelectorAll('[data-font-action]').forEach(button=>button.addEventListener('click',()=>apply(button.dataset.fontAction==='reset'?100:percent+(button.dataset.fontAction==='increase'?10:-10))));
 window.addEventListener('storage',e=>{if(e.key===key)apply(Number(e.newValue||100),false);});
 window.addEventListener('message',e=>{
  if(embedded&&e.source===parent&&e.data?.type==='agentsplc-reading-size'&&typeof e.data.percent==='number')apply(e.data.percent,false);
  const frame=document.querySelector('iframe.guide-frame');
  if(frame&&e.source===frame.contentWindow&&e.data?.type==='agentsplc-guide-height'&&Number.isFinite(e.data.height)&&e.data.height>0)frame.style.height=Math.min(100000,Math.ceil(e.data.height)+4)+'px';
 });
 document.querySelectorAll('iframe.guide-frame').forEach(frame=>frame.addEventListener('load',()=>apply(percent,false)));
 if(embedded){new ResizeObserver(reportHeight).observe(document.body);window.addEventListener('load',reportHeight);}
 window.agentsPLCReading={apply,get percent(){return percent;}};
 apply(percent,false);
})();
