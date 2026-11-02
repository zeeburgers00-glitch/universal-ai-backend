export type ResearchSource={title:string;url:string;content:string};
export type ResearchResult={answer:string;sources:ResearchSource[]};
export async function researchTopic(topic:string,niche:string):Promise<ResearchResult>{
 const key=process.env.TAVILY_API_KEY;
 if(!key)throw new Error("Research provider is not configured: TAVILY_API_KEY is missing");
 const response=await fetch("https://api.tavily.com/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({api_key:key,query:topic+"; niche: "+niche,search_depth:"advanced",max_results:8,include_answer:true,include_raw_content:false})});
 if(!response.ok)throw new Error("Research provider returned HTTP "+response.status);
 const data=await response.json() as {answer?:string;results?:{title?:string;url?:string;content?:string}[]};
 const sources=(data.results||[]).filter(item=>item.url&&item.title).map(item=>({title:String(item.title),url:String(item.url),content:String(item.content||"").slice(0,1600)}));
 if(sources.length<3)throw new Error("Research returned fewer than three usable source URLs; publishing was blocked");
 return {answer:String(data.answer||""),sources};
}