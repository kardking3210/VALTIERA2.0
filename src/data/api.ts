const configuredBase=import.meta.env.VITE_MARKET_DATA_API_URL?.trim();
const base=(configuredBase||(import.meta.env.DEV?'http://127.0.0.1:8000':'')).replace(/\/$/,'');
export const apiBase=base;
export function authToken(){return localStorage.getItem('valtiera_token')||''}
export async function api<T=any>(path:string,options:RequestInit={}):Promise<T>{
 if(!base)throw new Error('The VALTIERA API is not connected. Set VITE_MARKET_DATA_API_URL in the Vercel project settings, then redeploy.');
 const headers=new Headers(options.headers); if(options.body!==undefined&&!headers.has('Content-Type'))headers.set('Content-Type','application/json'); const token=authToken(); if(token)headers.set('Authorization',`Bearer ${token}`);
 const res=await fetch(`${base}${path}`,{...options,headers}); const payload=await res.json().catch(()=>({detail:res.statusText})); if(!res.ok)throw new Error(payload.detail||`Request failed (${res.status})`); return payload as T;
}
export function post<T=any>(path:string,body:unknown){return api<T>(path,{method:'POST',body:JSON.stringify(body)})}
export function put<T=any>(path:string,body:unknown){return api<T>(path,{method:'PUT',body:JSON.stringify(body)})}
