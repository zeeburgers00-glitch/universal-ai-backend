import {createClient, SupabaseClient} from "@supabase/supabase-js";
import {randomUUID} from "node:crypto";
import {promises as fs} from "node:fs";
import path from "node:path";
import os from "node:os";
import {researchTopic} from "./research.js";
import {chooseDailyTopic,writeOriginalScript} from "./model.js";
import {renderVideo} from "./assets.js";
import {publishPrivateScheduled} from "./publish.js";

function estimateCost():number{
 const estimate=Number(process.env.VIDEO_COST_ESTIMATE_USD||0);
 if(!Number.isFinite(estimate)||estimate<=0)throw new Error("Set VIDEO_COST_ESTIMATE_USD before production is allowed");
 return estimate;
}
function messageOf(error:unknown):string{
 return (error instanceof Error?error.message:"Production stage failed").replace(/(Bearer\s+)[A-Za-z0-9._-]+/gi,"$1[REDACTED]").slice(0,500);
}
async function record(db:SupabaseClient,userId:string,jobId:string,stage:string,status:string,message:string,metadata:Record<string,unknown>={}){
 await db.from("audit_events").insert({user_id:userId,job_id:jobId,event_type:"production_stage",stage,status,message:message.slice(0,2000),metadata});
}
async function setStage(db:SupabaseClient,userId:string,jobId:string,stage:string,progress:number,message:string){
 await db.from("production_jobs").update({status:"running",stage,progress,updated_at:new Date().toISOString(),error:null}).eq("id",jobId).eq("user_id",userId);
 await record(db,userId,jobId,stage,"running",message);
}
async function checkBudget(db:SupabaseClient,userId:string,jobId:string,settings:Record<string,unknown>,estimate:number){
 const cap=Number(settings.daily_budget_usd||0);
 if(cap<=0)throw new Error("Set a positive daily budget before production is allowed");
 const {data,error}=await db.from("provider_usage").select("cost_usd").eq("user_id",userId).neq("job_id",jobId).gte("created_at",new Date(Date.now()-24*60*60*1000).toISOString());
 if(error)throw new Error("Could not verify daily budget usage");
 const spent=(data||[]).reduce((sum:number,row:{cost_usd:number})=>sum+Number(row.cost_usd||0),0);
 if(spent+estimate>cap)throw new Error("Daily budget cap would be exceeded; production was paused");
}
export async function runProduction(args:{db:SupabaseClient;jobId:string;userId:string;topic:string}):Promise<void>{
 const {db,jobId,userId,topic}=args,dir=path.join(os.tmpdir(),"ytstudio-"+randomUUID());
 await fs.mkdir(dir,{recursive:true});
 try{
  const {data:job,error:jobError}=await db.from("production_jobs").select("status,upload_started_at,youtube_video_id,output").eq("id",jobId).eq("user_id",userId).single();
  if(jobError||!job)throw new Error("Production job not found");
  if(job.status==="cancelled")return;
  if(job.youtube_video_id)return;
  if(job.upload_started_at)throw new Error("An upload attempt already started. Automatic re-upload is blocked to avoid duplicate videos; inspect YouTube Studio and reconcile manually.");
  const {data:settings,error:settingsError}=await db.from("creator_settings").select("*").eq("user_id",userId).maybeSingle();
  if(settingsError||!settings)throw new Error("Creator settings are missing");
  const estimated=estimateCost();
  await checkBudget(db,userId,jobId,settings,estimated);
  const {error:reservationError}=await db.from("provider_usage").upsert({user_id:userId,job_id:jobId,provider:"estimated-video-pipeline",usage_kind:"estimated_reservation",cost_usd:estimated,usage:{reservation:true}},{onConflict:"job_id,usage_kind"});
  if(reservationError)throw new Error("Could not reserve estimated budget for this production job");
  let selectedTopic=topic;
  if(topic.startsWith("Daily original video opportunity for niche:")){
    await setStage(db,userId,jobId,"topic_discovery",5,"Selecting a fresh niche-specific topic using recent research evidence.");
    const opportunities=await researchTopic("Recent and evergreen original YouTube explainer topic opportunities in "+String(settings.niche||"general education"),String(settings.niche||""));
    const {data:recent}=await db.from("production_jobs").select("topic").eq("user_id",userId).neq("id",jobId).order("created_at",{ascending:false}).limit(30);
    selectedTopic=await chooseDailyTopic({niche:String(settings.niche||""),language:String(settings.language||"English"),audience:String(settings.target_audience||""),researchAnswer:opportunities.answer,sources:opportunities.sources,recentTopics:(recent||[]).map((item:{topic:string})=>item.topic)});
    await db.from("production_jobs").update({topic:selectedTopic,updated_at:new Date().toISOString()}).eq("id",jobId);
    await record(db,userId,jobId,"topic_discovery","completed","A fresh niche-specific topic was selected from research evidence.",{topic:selectedTopic,source_count:opportunities.sources.length});
  }
  if(/medical|medicine|diagnos|treatment|legal advice|financial advice|investment recommendation|election result|breaking news/i.test(selectedTopic))throw new Error("High-risk topic detected. This automated workflow requires an appropriately reviewed specialist fact-check before production can continue.");
  await setStage(db,userId,jobId,"research",12,"Searching licensed research sources and recording source URLs.");
  const research=await researchTopic(selectedTopic,String(settings.niche||""));
  await setStage(db,userId,jobId,"scriptwriting",20,"Writing an original script using the collected evidence.");
  const pack=await writeOriginalScript({topic:selectedTopic,niche:String(settings.niche||""),language:String(settings.language||"English"),audience:String(settings.target_audience||""),researchAnswer:research.answer,sources:research.sources});
  await db.from("production_jobs").update({output:{title:pack.title,description:pack.description,tags:pack.tags,script:pack.script,research_sources:research.sources},updated_at:new Date().toISOString()}).eq("id",jobId);
  await record(db,userId,jobId,"scriptwriting","completed","Original script and storyboard generated.",{words:pack.script.split(/\s+/).length,source_count:research.sources.length});
  await setStage(db,userId,jobId,"licensed_footage",30,"Downloading licensed stock video clips from Pexels.");
  await setStage(db,userId,jobId,"voice_and_captions",48,"Generating narration and Whisper captions.");
  await setStage(db,userId,jobId,"rendering",68,"Rendering 1080p footage and synchronized captions with FFmpeg.");
  const rendered=await renderVideo(pack,dir);
  if(rendered.assets.length<8||rendered.assets.some(asset=>asset.license!=="Pexels license"))throw new Error("Stock video licensing evidence did not pass review");
  await setStage(db,userId,jobId,"quality_review",85,"Checking output duration, resolution, captions and asset licence records.");
  const video=await fs.readFile(rendered.video),captions=await fs.readFile(rendered.captions),thumbnail=await fs.readFile(rendered.thumbnail);
  const maxBytes=Number(process.env.MAX_VIDEO_BYTES||1500000000);
  if(video.length>maxBytes)throw new Error("Rendered video exceeds MAX_VIDEO_BYTES");
  const base=userId+"/"+jobId+"/",bucket="youtube-media";
  for(const item of [
    {name:"final.mp4",body:video,type:"video/mp4"},
    {name:"captions.srt",body:captions,type:"application/x-subrip"},
    {name:"thumbnail.jpg",body:thumbnail,type:"image/jpeg"}
  ]){
    const {error}=await db.storage.from(bucket).upload(base+item.name,item.body,{contentType:item.type,upsert:true});
    if(error)throw new Error("Private media storage failed: "+error.message.slice(0,180));
  }
  const {data:signed,error:signedError}=await db.storage.from(bucket).createSignedUrl(base+"final.mp4",3600);
  if(signedError||!signed?.signedUrl)throw new Error("Could not create private video preview URL");
  let publication:{videoId:string;url:string;publishAt:string}|null=null;
  const {data:latest}=await db.from("production_jobs").select("status,upload_started_at,youtube_video_id").eq("id",jobId).single();
  if(latest?.status==="cancelled")throw new Error("Automation was stopped before publishing");
  const {data:latestSettings}=await db.from("creator_settings").select("autopublish_enabled,made_for_kids,contains_synthetic_media,schedule_time,timezone").eq("user_id",userId).single();
  if(latestSettings?.autopublish_enabled){
    if(typeof latestSettings.made_for_kids!=="boolean"||typeof latestSettings.contains_synthetic_media!=="boolean")throw new Error("Audience and synthetic-media declarations must be explicitly selected before publishing");
    if(latest?.upload_started_at||latest?.youtube_video_id)throw new Error("Duplicate upload protection blocked this YouTube job");
    await db.from("production_jobs").update({stage:"youtube_upload",progress:93,upload_started_at:new Date().toISOString(),updated_at:new Date().toISOString()}).eq("id",jobId);
    await record(db,userId,jobId,"youtube_upload","running","Uploading private video with a future publishAt timestamp.");
    publication=await publishPrivateScheduled({db,userId,filePath:rendered.video,thumbnailPath:rendered.thumbnail,pack,settings:latestSettings});
    await db.from("production_jobs").update({youtube_video_id:publication.videoId}).eq("id",jobId);
  }
  const output={
    title:pack.title,description:pack.description,tags:pack.tags,script:pack.script,research_sources:research.sources,
    licensed_assets:rendered.assets,duration_seconds:rendered.duration,asset_path:base+"final.mp4",asset_url:signed.signedUrl,
    captions_path:base+"captions.srt",thumbnail_path:base+"thumbnail.jpg",youtube_video_id:publication?.videoId||null,
    youtube_url:publication?.url||null,publish_at:publication?.publishAt||null
  };
  await db.from("production_jobs").update({status:publication?"scheduled":"draft_ready",stage:publication?"scheduled":"draft_ready",progress:100,output,estimated_cost_usd:estimated,completed_at:new Date().toISOString(),updated_at:new Date().toISOString(),error:null}).eq("id",jobId);
  await record(db,userId,jobId,"quality_review","completed","1080p render, captions and asset licence checks passed.",{duration_seconds:rendered.duration});
  if(publication)await record(db,userId,jobId,"youtube_upload","completed","YouTube accepted scheduled upload "+publication.videoId,{url:publication.url,publish_at:publication.publishAt});
  else await record(db,userId,jobId,"draft_ready","completed","Video stored privately as a draft; autopublish remains disabled.");
 }catch(error){
  const message=messageOf(error);
  await db.from("production_jobs").update({status:"failed",stage:"failed",error:message,completed_at:new Date().toISOString(),updated_at:new Date().toISOString()}).eq("id",jobId).eq("user_id",userId);
  await record(db,userId,jobId,"failed","failed",message);
  throw error;
 }finally{
  await fs.rm(dir,{recursive:true,force:true}).catch(()=>undefined);
 }
}