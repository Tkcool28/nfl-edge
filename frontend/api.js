export class ApiError extends Error { constructor(status,message,payload=null){ super(message||`Request failed (${status})`); this.name='ApiError'; this.status=status; this.payload=payload; } }
function base(x){ return x ? String(x).replace(/\/$/,'') : ''; }
export class ApiClient {
  constructor({baseUrl='',fetchImpl}={}){ const impl=fetchImpl??(typeof globalThis.fetch==='function'?globalThis.fetch.bind(globalThis):null); if(typeof impl!=='function') throw new TypeError('fetch implementation required'); this.baseUrl=base(baseUrl); this.fetchImpl=impl; }
  async request(path,{method='GET',body,headers={},signal}={}){
    const init={method,credentials:'include',cache:'no-store',headers:{Accept:'application/json',...headers},signal};
    if(body!==undefined){ init.headers['Content-Type']='application/json'; init.body=JSON.stringify(body); }
    let r; try{ r=await this.fetchImpl(`${this.baseUrl}${path}`,init); }catch(e){ throw new ApiError(0,'Backend unavailable',{cause:String(e)}); }
    if(r.status===204) return null;
    const ct=r.headers?.get?.('content-type')||''; let payload=null;
    try{ payload=ct.includes('application/json')?await r.json():await r.text(); }catch{}
    if(!r.ok) throw new ApiError(r.status,payload&&typeof payload==='object'?payload.detail:null,payload);
    return payload;
  }
  health(){return this.request('/api/v1/health');} register(username,password){return this.request('/api/v1/auth/register',{method:'POST',body:{username,password}});} login(username,password){return this.request('/api/v1/auth/login',{method:'POST',body:{username,password}});} logout(){return this.request('/api/v1/auth/logout',{method:'POST'});} me(){return this.request('/api/v1/auth/me');}
  profile(){return this.request('/api/v1/profile');} updateProfile(body){return this.request('/api/v1/profile',{method:'PUT',body});} productLatest(){return this.request('/api/v1/product/latest');} games(){return this.request('/api/v1/games');} game(id){return this.request(`/api/v1/games/${encodeURIComponent(id)}`);} evaluateOffer(body){return this.request('/api/v1/evaluate-offer',{method:'POST',body});}
  wagers(params={}){const q=new URLSearchParams(); Object.entries(params).forEach(([k,v])=>{if(v!==undefined&&v!==null&&v!=='')q.set(k,v)}); return this.request(`/api/v1/wagers${q.size?`?${q}`:''}`);} wager(id){return this.request(`/api/v1/wagers/${encodeURIComponent(id)}`);} createWager(body){return this.request('/api/v1/wagers',{method:'POST',body});} patchWager(id,body){return this.request(`/api/v1/wagers/${encodeURIComponent(id)}`,{method:'PATCH',body});}
}
