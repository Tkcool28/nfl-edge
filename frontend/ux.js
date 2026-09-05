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
const gameCache=new Map();
let activeGameId=null;

const visualStyle=document.createElement('style');
visualStyle.id='nfl-edge-visual-assets';
visualStyle.textContent=`
.asset-shell{position:relative;display:inline-grid;place-items:center;overflow:hidden;flex:0 0 auto;border:1px solid var(--line);background:var(--surface-2);color:var(--ink-3)}
.asset-img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block}.asset-img[hidden]{display:none}.asset-fallback{font-weight:900;letter-spacing:.04em;line-height:1;text-align:center}
.team-logo-shell{width:24px;height:24px;border-radius:7px}.team-logo-shell .asset-img{padding:2px}.team-logo-shell .asset-fallback{font-size:7px}
.game-matchup-visual{display:inline-flex;align-items:center;gap:5px;min-width:0;white-space:nowrap}.game-team{display:inline-flex;align-items:center;gap:4px;min-width:0}.game-team-code{font-weight:800}.game-at{color:var(--ink-3);font-size:.8em}
.detail-matchup-visual{display:flex;align-items:center;flex-wrap:wrap;gap:9px;margin:8px 0 4px}.detail-team{display:inline-flex;align-items:center;gap:8px}.detail-team .team-logo-shell{width:42px;height:42px;border-radius:11px}.detail-team .team-logo-shell .asset-img{padding:4px}.detail-team .team-logo-shell .asset-fallback{font-size:10px}.detail-team-code{font-weight:850}.detail-at{color:var(--ink-3);font-size:.72em}
.qb-card.visual-qb{display:grid;grid-template-columns:58px minmax(0,1fr);align-items:center;gap:10px;min-height:78px}.qb-photo-shell{width:58px;height:62px;border-radius:12px}.qb-photo-shell .asset-img{object-fit:cover;object-position:50% 12%;background:var(--surface-2)}.qb-photo-shell .asset-fallback{font-size:16px}.qb-copy{display:flex;flex-direction:column;min-width:0}.qb-copy strong{line-height:1.2}.qb-copy small{line-height:1.35;margin-top:3px}
[data-theme="extreme"] .asset-shell{border-radius:0;box-shadow:none}[data-theme="extreme"] .qb-photo-shell{border-color:#363b36}[data-theme="fancy"] .asset-shell{border-color:#7b603d}
@media(max-width:340px){.team-logo-shell{width:21px;height:21px}.game-matchup-visual{gap:3px}.detail-team .team-logo-shell{width:36px;height:36px}.detail-matchup-visual{gap:6px}.qb-card.visual-qb{grid-template-columns:50px minmax(0,1fr);gap:8px}.qb-photo-shell{width:50px;height:56px}}
`;
document.head.append(visualStyle);

const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtLine=v=>v==null||v===''?'':`${Number(v)>0?'+':''}${Number(v)}`;
const fmtPrice=v=>v==null||v===''?'—':`${Number(v)>0?'+':''}${Number(v)}`;
const marketType=market=>String(market).toLowerCase()==='moneyline'?'ML':'SPREAD';
const marketLabel=(market,offer)=>{
  const selection=esc(offer.selection||'');
  const line=String(market).toLowerCase()==='moneyline'?'':` ${fmtLine(offer.line)}`;
  return `${selection}${line}`.trim();
};
const teamCode=team=>String(team||'').trim().toUpperCase();
const espnTeamCode=team=>({LA:'lar',LAR:'lar',WAS:'wsh',WSH:'wsh',JAC:'jax',JAX:'jax'}[teamCode(team)]||teamCode(team).toLowerCase());
const teamLogoUrl=team=>teamCode(team)?`https://a.espncdn.com/i/teamlogos/nfl/500/${encodeURIComponent(espnTeamCode(team))}.png`:null;
const qbHeadshotUrl=qb=>qb?.sleeper_player_id?`https://sleepercdn.com/content/nfl/players/thumb/${encodeURIComponent(qb.sleeper_player_id)}.jpg`:null;
const initials=name=>String(name||'QB').trim().split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('').toUpperCase()||'QB';
const assetMarkup=(url,fallback,className,label='')=>`<span class="asset-shell ${className}"><span class="asset-fallback">${esc(fallback)}</span>${url?`<img class="asset-img" data-asset-img src="${esc(url)}" alt="" aria-hidden="true" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-asset-label="${esc(label)}">`:''}</span>`;
const teamMarkup=(team,detail=false)=>{const code=teamCode(team);return `<span class="${detail?'detail-team':'game-team'}">${assetMarkup(teamLogoUrl(code),code,detail?'team-logo-shell':'team-logo-shell',`${code} logo`)}<span class="${detail?'detail-team-code':'game-team-code'}">${esc(code)}</span></span>`};

function wireAssetImages(scope){
  scope.querySelectorAll('img[data-asset-img]:not([data-asset-wired])').forEach(img=>{
    img.dataset.assetWired='1';
    const fail=()=>{img.hidden=true;img.closest('.asset-shell')?.classList.add('asset-failed')};
    const load=()=>{img.hidden=false;img.closest('.asset-shell')?.classList.add('asset-loaded')};
    if(img.complete){img.naturalWidth?load():fail();return}
    img.addEventListener('load',load,{once:true});img.addEventListener('error',fail,{once:true});
  });
}

async function getGame(id){
  const key=String(id||'');
  const cached=gameCache.get(key);
  if(cached)return cached;
  const pending=api.game(key).then(response=>response?.game||response).catch(error=>{gameCache.delete(key);throw error});
  gameCache.set(key,pending);
  return pending;
}
function clearGameCache(){gameCache.clear()}
document.getElementById('refresh-btn')?.addEventListener('click',clearGameCache,true);
window.addEventListener('online',clearGameCache);

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
function renderGameCardVisuals(card,game){
  const matchup=card.querySelector('.gmatch > span:first-child');
  if(!matchup||matchup.classList.contains('game-matchup-visual'))return;
  matchup.classList.add('game-matchup-visual');
  matchup.innerHTML=`${teamMarkup(game.away_team)}<span class="game-at">@</span>${teamMarkup(game.home_team)}`;
  wireAssetImages(matchup);
}

async function hydrateGameCard(card){
  const id=card?.dataset?.game;
  if(!id||loadingCards.has(card))return;
  if(card.querySelector('.game-compare')&&card.querySelector('.game-matchup-visual'))return;
  loadingCards.add(card);
  try{
    const game=await getGame(id);
    if(card.isConnected){renderGameCardVisuals(card,game);renderComparisonRows(card,gameComparisonRows(game))}
  }catch{}finally{loadingCards.delete(card)}
}
function hydrateVisibleGameCards(){document.querySelectorAll('#games-list .gcard[data-game]').forEach(hydrateGameCard)}
const games=document.getElementById('games-list');
if(games){
  games.addEventListener('click',e=>{const card=e.target.closest?.('.gcard[data-game]');if(card)activeGameId=card.dataset.game},true);
  hydrateVisibleGameCards();
  new MutationObserver(hydrateVisibleGameCards).observe(games,{childList:true,subtree:true});
}

function decorateQbCard(card,qb){
  if(!card||card.classList.contains('visual-qb'))return;
  const copy=document.createElement('span');copy.className='qb-copy';
  while(card.firstChild)copy.append(card.firstChild);
  const shell=document.createElement('span');shell.innerHTML=assetMarkup(qbHeadshotUrl(qb),initials(qb?.expected_starter),'qb-photo-shell',qb?.expected_starter||'Quarterback');
  card.append(shell.firstElementChild,copy);card.classList.add('visual-qb');wireAssetImages(card);
}
function decorateDetail(card,game){
  if(!card||!game)return;
  const heading=card.querySelector('h2');
  if(heading&&!heading.classList.contains('detail-matchup-visual')){
    heading.classList.add('detail-matchup-visual');
    heading.innerHTML=`${teamMarkup(game.away_team,true)}<span class="detail-at">@</span>${teamMarkup(game.home_team,true)}`;
    wireAssetImages(heading);
  }
  const qbCards=[...card.querySelectorAll('.qb-grid .qb-card')];
  decorateQbCard(qbCards[0],game.quarterbacks?.away||{});
  decorateQbCard(qbCards[1],game.quarterbacks?.home||{});
  card.dataset.visualGame=String(game.game_id||activeGameId||'');
}
async function hydrateDetail(){
  const card=document.getElementById('detail-card');
  if(!card||!activeGameId||card.querySelector('.loading-card')||card.dataset.visualGame===String(activeGameId))return;
  try{const game=await getGame(activeGameId);if(card.isConnected&&!card.querySelector('.loading-card'))decorateDetail(card,game)}catch{}
}
const detail=document.getElementById('detail-card');
if(detail)new MutationObserver(hydrateDetail).observe(detail,{childList:true,subtree:true});
