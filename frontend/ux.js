import {ApiClient} from './api.js';
import {gameComparisonRows} from './market-compare.js';

const THEMES=['light','cream','slate','mint','fancy','modern','extreme'];
const THEME_KEY='nfl-edge-theme-v1';
const COMPARE_KEY='nfl-edge-pinny-compare-v1';
const root=document.documentElement;
const body=document.body;
const trigger=document.getElementById('theme-trigger');
const popover=document.getElementById('theme-popover');
const tiles=[...document.querySelectorAll('[data-theme-choice]')];
const compareToggle=document.getElementById('compare-toggle');
const compareInfo=document.getElementById('compare-info');
const compareHelp=document.getElementById('compare-help');
const compareHelpClose=document.getElementById('compare-help-close');
const api=new ApiClient({baseUrl:globalThis.NFL_EDGE_API_BASE||''});
const loadingCards=new WeakSet();

const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtLine=v=>v==null||v===''?'':`${Number(v)>0?'+':''}${Number(v)}`;
const fmtPrice=v=>v==null||v===''?'—':`${Number(v)>0?'+':''}${Number(v)}`;
const marketType=market=>String(market).toLowerCase()==='moneyline'?'ML':'SPREAD';
const marketLabel=(market,offer)=>{
  const selection=esc(offer.selection||'');
  const line=String(market).toLowerCase()==='moneyline'?'':` ${fmtLine(offer.line)}`;
  return `${selection}${line}`.trim();
};

function applyTheme(theme){
  const next=THEMES.includes(theme)?theme:'light';
  root.dataset.theme=next;
  tiles.forEach(tile=>tile.setAttribute('aria-pressed',tile.dataset.themeChoice===next?'true':'false'));
  try{localStorage.setItem(THEME_KEY,next)}catch{}
}
function closeTheme(){if(popover){popover.hidden=true;trigger?.setAttribute('aria-expanded','false')}}
try{applyTheme(localStorage.getItem(THEME_KEY)||'light')}catch{applyTheme('light')}
trigger?.addEventListener('click',e=>{e.stopPropagation();popover.hidden=!popover.hidden;trigger.setAttribute('aria-expanded',popover.hidden?'false':'true')});
tiles.forEach(tile=>tile.addEventListener('click',()=>{applyTheme(tile.dataset.themeChoice);closeTheme()}));
document.addEventListener('click',e=>{if(popover&&!popover.hidden&&!popover.contains(e.target)&&!trigger?.contains(e.target))closeTheme()});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeTheme()});

function setCompare(enabled,persist=true){
  body.classList.toggle('pinny-compare-on',enabled);
  compareToggle?.classList.toggle('is-on',enabled);
  compareToggle?.setAttribute('aria-checked',enabled?'true':'false');
  if(persist){try{localStorage.setItem(COMPARE_KEY,enabled?'on':'off')}catch{}}
}
let compareEnabled=true;
try{compareEnabled=localStorage.getItem(COMPARE_KEY)!=='off'}catch{}
setCompare(compareEnabled,false);
compareToggle?.addEventListener('click',()=>{compareEnabled=!compareEnabled;setCompare(compareEnabled)});
compareInfo?.addEventListener('click',()=>compareHelp?.showModal());
compareHelpClose?.addEventListener('click',()=>compareHelp?.close());
compareHelp?.addEventListener('click',e=>{if(e.target===compareHelp)compareHelp.close()});

function renderComparisonRows(card,rows){
  if(!rows.length||card.querySelector('.game-compare'))return;
  const wrapper=document.createElement('span');
  wrapper.className='game-compare';
  wrapper.setAttribute('aria-label','DraftKings and FanDuel moneyline and spread offers compared with hidden Pinnacle benchmark');
  wrapper.innerHTML=rows.map(row=>`<span class="game-compare-row cmp-${esc(row.status)}"><span class="game-compare-book">${row.book==='DRAFTKINGS'?'DK':'FD'}</span><span class="game-compare-offer"><span class="game-compare-type">${marketType(row.market)}</span><span class="game-compare-market">${marketLabel(row.market,row.retail)}</span><span class="game-compare-label">${esc(row.label)}</span></span><span class="game-compare-price">${fmtPrice(row.retail.price)}</span></span>`).join('');
  card.append(wrapper);
}

async function hydrateGameCard(card){
  const id=card?.dataset?.game;
  if(!id||card.querySelector('.game-compare')||loadingCards.has(card))return;
  loadingCards.add(card);
  try{
    const response=await api.game(id);
    const game=response?.game||response;
    if(card.isConnected)renderComparisonRows(card,gameComparisonRows(game));
  }catch{}finally{loadingCards.delete(card)}
}
function hydrateVisibleGameCards(){document.querySelectorAll('#games-list .gcard[data-game]').forEach(hydrateGameCard)}
const games=document.getElementById('games-list');
if(games){hydrateVisibleGameCards();new MutationObserver(hydrateVisibleGameCards).observe(games,{childList:true,subtree:true})}

/* Ultra changes stake size only. Require an explicit acknowledgement before the selector keeps it. */
let ultraPending=null;
function ultraDialog(){
  let dialog=document.getElementById('ultra-risk-warning');
  if(dialog)return dialog;
  dialog=document.createElement('dialog');
  dialog.id='ultra-risk-warning';
  dialog.className='risk-warning';
  dialog.setAttribute('aria-labelledby','ultra-risk-title');
  dialog.innerHTML=`<section class="risk-warning-card"><span class="risk-warning-kicker">Higher bankroll exposure</span><h2 id="ultra-risk-title">Ultra staking</h2><p>Choosing Ultra changes stake size, not the wager. It does not increase win probability, improve the model's edge, or improve the expected percentage return.</p><p class="risk-warning-emphasis">Only the dollar swings get larger — both wins and losses.</p><p>Use Ultra only when you intentionally want more of your bankroll at risk on the same recommendations.</p><div class="risk-warning-actions"><button class="btn-secondary" type="button" data-ultra-back>Go back</button><button class="btn-primary" type="button" data-ultra-confirm>Use Ultra</button></div></section>`;
  document.body.append(dialog);
  const cancel=()=>{if(ultraPending?.select?.isConnected)ultraPending.select.value=ultraPending.previous;ultraPending=null;dialog.close()};
  dialog.querySelector('[data-ultra-back]').addEventListener('click',cancel);
  dialog.querySelector('[data-ultra-confirm]').addEventListener('click',()=>{if(ultraPending?.select?.isConnected)ultraPending.select.dataset.previousRisk='Ultra';ultraPending=null;dialog.close()});
  dialog.addEventListener('cancel',e=>{e.preventDefault();cancel()});
  dialog.addEventListener('click',e=>{if(e.target===dialog)cancel()});
  return dialog;
}
function rememberRisk(select){if(select?.id==='risk')select.dataset.previousRisk=select.value}
document.addEventListener('pointerdown',e=>rememberRisk(e.target));
document.addEventListener('focusin',e=>{if(e.target?.id==='risk'&&!e.target.dataset.previousRisk)rememberRisk(e.target)});
document.addEventListener('change',e=>{
  const select=e.target;
  if(select?.id!=='risk')return;
  const previous=select.dataset.previousRisk||'Normal';
  if(select.value!=='Ultra'){select.dataset.previousRisk=select.value;return}
  if(previous==='Ultra')return;
  ultraPending={select,previous};
  ultraDialog().showModal();
});
