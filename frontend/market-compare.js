const BOOKS=['DRAFTKINGS','FANDUEL'];
const BOARD_MARKETS=['moneyline','spread'];
const same=(a,b)=>String(a??'').trim().toUpperCase()===String(b??'').trim().toUpperCase();
const num=v=>v==null||v===''?null:Number(v);

export function compareOffer(market,retail,pinny){
  if(!retail||!pinny)return null;
  const rp=num(retail.price),pp=num(pinny.price);
  if(!Number.isFinite(rp)||!Number.isFinite(pp))return null;
  const priceCmp=rp===pp?0:rp>pp?1:-1;
  let lineCmp=0;
  const type=String(market||'').toLowerCase();
  if(type!=='moneyline'){
    const rl=num(retail.line),pl=num(pinny.line);
    if(!Number.isFinite(rl)||!Number.isFinite(pl))return null;
    if(rl!==pl){
      if(type==='spread')lineCmp=rl>pl?1:-1;
      else if(type==='total'){
        const selection=String(retail.selection||'').toUpperCase();
        lineCmp=selection==='OVER'?(rl<pl?1:-1):selection==='UNDER'?(rl>pl?1:-1):0;
      }
    }
  }
  if(priceCmp<0||lineCmp<0)return'worse';
  if(priceCmp>0&&lineCmp>0)return'both';
  if(lineCmp>0)return'line';
  if(priceCmp>0)return'price';
  return'same';
}

export function comparisonLabel(status){
  return{line:'better line',price:'better price',both:'better line + price',worse:'worse vs benchmark',same:'same as benchmark'}[status]||'';
}

export function findPinnyOffer(pinnyOffers,retail){
  return(pinnyOffers||[]).find(p=>same(p.selection,retail.selection))||null;
}

export function gameComparisonRows(game){
  const board=game?.market_board;
  if(!board)return[];
  const rows=[];
  for(const book of BOOKS){
    for(const market of BOARD_MARKETS){
      const retailOffers=board?.[market]?.[book]||[];
      const pinnyOffers=board?.[market]?.PINNACLE||[];
      for(const retail of retailOffers){
        const pinny=findPinnyOffer(pinnyOffers,retail);
        const status=compareOffer(market,retail,pinny);
        if(status)rows.push({book,market,retail,pinny,status,label:comparisonLabel(status)});
      }
    }
  }
  return rows;
}
