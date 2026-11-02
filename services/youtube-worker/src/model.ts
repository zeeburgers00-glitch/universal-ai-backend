import type {ResearchSource} from "./research.js";
export type ScriptPack={title:string;description:string;tags:string[];script:string;scenes:{query:string;purpose:string}[];research_notes?:string};
export async function writeOriginalScript(args:{topic:string;niche:string;language:string;audience:string;researchAnswer:string;sources:ResearchSource[]}):Promise<ScriptPack>{
 const key=process.env.MODEL_API_KEY,base=(process.env.MODEL_BASE_URL||"https://api.openai.com/v1").replace(/\/$/,""),model=process.env.MODEL_NAME;
 if(!key||!model)throw new Error("Model provider is not configured: set MODEL_API_KEY and MODEL_NAME");
 const response=await fetch(base+"/chat/completions",{method:"POST",headers:{"Authorization":"Bearer "+key,"Content-Type":"application/json"},body:JSON.stringify({
  model,temperature:0.65,max_tokens:8500,response_format:{type:"json_object"},
  messages:[
   {role:"system",content:"You are an evidence-led YouTube documentary writer. Create original educational work; never copy or closely paraphrase another creator. Use only the supplied research evidence for factual claims, and put source URLs into the description. If evidence is insufficient, return research_notes explaining the gap. Return valid JSON with fields title, description, tags, script, scenes. Script must be a complete 10–15 minute narration in the requested language, roughly 1500–1900 words. Scenes must contain 12–18 distinct stock-video search queries, never still-image prompts. Do not invent quotes, statistics, or sources."},
   {role:"user",content:JSON.stringify({topic:args.topic,niche:args.niche,language:args.language,audience:args.audience,research_answer:args.researchAnswer,sources:args.sources.map(s=>({title:s.title,url:s.url,excerpt:s.content})),requirements:{originality:true,source_urls_in_description:true,stock_video_queries_only:true}})}
  ]
 })});
 if(!response.ok)throw new Error("Model provider returned HTTP "+response.status);
 const data=await response.json() as {choices?:{message?:{content?:string}}[]};
 const raw=data.choices?.[0]?.message?.content||"";
 let pack:ScriptPack;
 try{pack=JSON.parse(raw) as ScriptPack}catch{throw new Error("Model provider did not return valid structured JSON")};
 if(!pack.title||!pack.description||!pack.script||!Array.isArray(pack.tags)||!Array.isArray(pack.scenes))throw new Error("Generated script is missing required fields");
 if(pack.script.split(/\s+/).length<1400)throw new Error("Generated narration is shorter than the 10–15 minute production target");
 if(pack.scenes.length<8)throw new Error("Storyboard returned too few stock-video scenes");
 if(pack.research_notes)throw new Error("Research review flagged insufficient evidence");
 pack.scenes=pack.scenes.slice(0,18);
 pack.description=(pack.description+"\n\nResearch sources:\n"+args.sources.map(s=>"- "+s.title+": "+s.url).join("\n")).slice(0,4900);
 return pack;
}
export async function chooseDailyTopic(args:{niche:string;language:string;audience:string;researchAnswer:string;sources:ResearchSource[];recentTopics:string[]}):Promise<string>{
 const key=process.env.MODEL_API_KEY,base=(process.env.MODEL_BASE_URL||"https://api.openai.com/v1").replace(/\/$/,""),model=process.env.MODEL_NAME;
 if(!key||!model)throw new Error("Model provider is not configured: set MODEL_API_KEY and MODEL_NAME");
 const response=await fetch(base+"/chat/completions",{method:"POST",headers:{"Authorization":"Bearer "+key,"Content-Type":"application/json"},body:JSON.stringify({
  model,temperature:0.5,max_tokens:700,response_format:{type:"json_object"},
  messages:[
   {role:"system",content:"Choose one specific, compelling and original YouTube long-form topic for the niche. Base it on the evidence supplied; avoid recent topics in the list; do not invent trend numbers. Return JSON with topic and rationale. The topic must be clear enough to research independently."},
   {role:"user",content:JSON.stringify({niche:args.niche,language:args.language,audience:args.audience,research:args.researchAnswer,sources:args.sources.map(s=>({title:s.title,url:s.url,excerpt:s.content})),recent_topics:args.recentTopics})}
  ]
 })});
 if(!response.ok)throw new Error("Daily topic discovery model returned HTTP "+response.status);
 const data=await response.json() as {choices?:{message?:{content?:string}}[]};
 try{
  const result=JSON.parse(data.choices?.[0]?.message?.content||"") as {topic?:string};
  if(!result.topic||result.topic.length<12||result.topic.length>250)throw new Error("missing topic");
  return result.topic;
 }catch{throw new Error("Daily topic discovery did not return a valid topic")}
}
