export type ResearchSource={title:string;url:string;content:string};
export type ResearchResult={answer:string;sources:ResearchSource[]};
type SearchItem={title?:string;url?:string;content?:string};
function normalizeSources(items:SearchItem[]):ResearchSource[]{
 return items.filter(item=>item.url&&item.title).map(item=>({
  title:String(item.title),url:String(item.url),content:String(item.content||"").slice(0,1600)
 })).slice(0,8);
}
async function searchTavily(topic:string,niche:string,key:string):Promise<{answer:string;items:SearchItem[]}>{
 const response=await fetch("https://api.tavily.com/search",{
  method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({api_key:key,query:topic+"; niche: "+niche,search_depth:"advanced",max_results:8,include_answer:true,include_raw_content:false}),
  signal:AbortSignal.timeout(30000)
 });
 if(!response.ok)throw new Error("Tavily research provider returned HTTP "+response.status);
 const data=await response.json() as {answer?:string;results?:SearchItem[]};
 return {answer:String(data.answer||""),items:data.results||[]};
}
async function searchSearxng(topic:string,niche:string,base:string):Promise<{answer:string;items:SearchItem[]}>{
 let endpoint:URL;
 try{endpoint=new URL("/search",base)}catch{throw new Error("SEARXNG_BASE_URL must be a valid absolute URL");}
 if(!["http:","https:"].includes(endpoint.protocol)||endpoint.username||endpoint.password)
  throw new Error("SEARXNG_BASE_URL must use HTTP(S) and must not embed credentials");
 endpoint.searchParams.set("q",topic+"; niche: "+niche);
 endpoint.searchParams.set("format","json");
 endpoint.searchParams.set("safesearch","1");
 const response=await fetch(endpoint,{headers:{Accept:"application/json"},signal:AbortSignal.timeout(30000)});
 if(!response.ok)throw new Error("SearXNG research provider returned HTTP "+response.status+"; confirm JSON is enabled in search.formats");
 const data=await response.json() as {results?:SearchItem[]};
 return {answer:"",items:data.results||[]};
}
export async function researchTopic(topic:string,niche:string):Promise<ResearchResult>{
 const key=process.env.TAVILY_API_KEY?.trim();
 const searxng=process.env.SEARXNG_BASE_URL?.trim();
 if(!key&&!searxng)throw new Error("Research provider is not configured: set TAVILY_API_KEY or SEARXNG_BASE_URL");
 const result=key
  ? await searchTavily(topic,niche,key)
  : await searchSearxng(topic,niche,searxng!);
 const sources=normalizeSources(result.items);
 if(sources.length<3)throw new Error("Research returned fewer than three usable source URLs; publishing was blocked");
 return {answer:result.answer,sources};
}
