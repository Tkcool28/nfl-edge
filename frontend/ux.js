const THEMES=['light','cream','slate','mint','fancy','modern','extreme'];
const KEY='nfl-edge-theme-v1';
const root=document.documentElement;
const trigger=document.getElementById('theme-trigger');
const popover=document.getElementById('theme-popover');
const tiles=[...document.querySelectorAll('[data-theme-choice]')];
function apply(theme){
  const next=THEMES.includes(theme)?theme:'light';
  root.dataset.theme=next;
  tiles.forEach(tile=>tile.setAttribute('aria-pressed',tile.dataset.themeChoice===next?'true':'false'));
  try{localStorage.setItem(KEY,next)}catch{}
}
try{apply(localStorage.getItem(KEY)||'light')}catch{apply('light')}
function close(){popover.hidden=true;trigger.setAttribute('aria-expanded','false')}
trigger?.addEventListener('click',e=>{e.stopPropagation();popover.hidden=!popover.hidden;trigger.setAttribute('aria-expanded',popover.hidden?'false':'true')});
tiles.forEach(tile=>tile.addEventListener('click',()=>{apply(tile.dataset.themeChoice);close()}));
document.addEventListener('click',e=>{if(!popover.hidden&&!popover.contains(e.target)&&e.target!==trigger)close()});
document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
document.getElementById('account-quick-btn')?.addEventListener('click',()=>document.querySelector('[data-nav="account"]')?.click());
function relabelHeadlineActions(){
  document.querySelectorAll('#headlines [data-log]').forEach(button=>{if(button.textContent!=='Log Bet')button.textContent='Log Bet'});
  document.querySelectorAll('#headlines [data-signin]').forEach(button=>{if(button.textContent!=='Sign in to log bet')button.textContent='Sign in to log bet'});
}
const headlines=document.getElementById('headlines');
if(headlines){relabelHeadlineActions();new MutationObserver(relabelHeadlineActions).observe(headlines,{childList:true,subtree:true})}
