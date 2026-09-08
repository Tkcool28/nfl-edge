import {ApiClient,ApiError} from './api.js';

const api=new ApiClient({baseUrl:globalThis.NFL_EDGE_API_BASE||''});
let timer=null;

const usd=value=>value==null?'—':`$${Number(value).toFixed(2)}`;
const signedUsd=value=>{
  if(value==null)return'—';
  const n=Number(value);
  if(!Number.isFinite(n))return'—';
  return `${n>0?'+':n<0?'-':''}$${Math.abs(n).toFixed(2)}`;
};
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');

function host(){
  const view=document.getElementById('view-bets');
  const list=document.getElementById('wager-list');
  if(!view||!list)return null;
  let node=document.getElementById('bankroll-summary');
  if(!node){
    node=document.createElement('section');
    node.id='bankroll-summary';
    node.className='bank-hero bankroll-summary-card';
    node.setAttribute('aria-live','polite');
    view.insertBefore(node,list);
  }
  return node;
}

function render(summary){
  const node=host();
  if(!node)return;
  if(!summary){node.hidden=true;node.innerHTML='';return;}
  const legacy=Number(summary.legacy_untracked_wagers||0);
  node.hidden=false;
  node.innerHTML=`<div class="bank-label">Current bankroll</div><div class="account-name">${usd(summary.current_bankroll)}</div><div class="wager-money"><span>Settled P/L <strong>${signedUsd(summary.realized_pl)}</strong></span><span>Open stakes <strong>${usd(summary.open_stakes)}</strong></span></div><p class="section-sub">Open wagers reserve their stake. Wins return the full payout.</p>${legacy>0?`<p class="section-sub bankroll-legacy-note">${esc(legacy)} earlier wager${legacy===1?'':'s'} predate automatic bankroll tracking and are not retroactively applied.</p>`:''}`;
}

async function refresh(){
  try{
    const summary=await api.bankroll();
    render(summary);
  }catch(error){
    if(error instanceof ApiError&&error.status===401){render(null);return;}
    const node=host();
    if(node){node.hidden=false;node.innerHTML='<div class="empty-state">Bankroll summary temporarily unavailable.</div>'}
  }
}

function schedule(){clearTimeout(timer);timer=setTimeout(refresh,30)}

document.querySelector('[data-nav="bets"]')?.addEventListener('click',schedule);
const list=document.getElementById('wager-list');
if(list)new MutationObserver(schedule).observe(list,{childList:true,subtree:true,characterData:true});
window.addEventListener('online',schedule);
window.addEventListener('nfl-edge-bankroll-refresh',schedule);

// Keep the summary current even when Bets is the first authenticated view rendered.
refresh();
