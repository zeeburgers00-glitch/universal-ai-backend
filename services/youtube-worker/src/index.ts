import "dotenv/config";
import { Redis } from "ioredis";
import {Queue,Worker,Job} from "bullmq";
import {createClient} from "@supabase/supabase-js";
import {runProduction} from "./pipeline.js";
const redisUrl=process.env.REDIS_URL;
const supabaseUrl=process.env.SUPABASE_URL;
const serviceKey=process.env.SUPABASE_SERVICE_ROLE_KEY;
if(!redisUrl||!supabaseUrl||!serviceKey)throw new Error("Worker requires REDIS_URL, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY");
const connection=new Redis(redisUrl,{maxRetriesPerRequest:null,enableReadyCheck:true});
const db=createClient(supabaseUrl,serviceKey,{auth:{persistSession:false,autoRefreshToken:false}});
const queue=new Queue("youtube-production",{connection});
async function createDailyJob(userId:string):Promise<void>{
 const {data:settings}=await db.from("creator_settings").select("autopublish_enabled,niche").eq("user_id",userId).maybeSingle();
 if(!settings?.autopublish_enabled)return;
 const day=new Date().toISOString().slice(0,10),idem="daily-autopilot:"+userId+":"+day;
 const {data:existing}=await db.from("production_jobs").select("id,status").eq("user_id",userId).eq("idempotency_key",idem).maybeSingle();
 if(existing)return;
 const topic="Daily original video opportunity for niche: "+String(settings.niche||"General education");
 const {data,error}=await db.from("production_jobs").insert({user_id:userId,topic,idempotency_key:idem,status:"queued",stage:"daily_topic_discovery",progress:0}).select("id").single();
 if(error)throw error;
 await queue.add("produce-video",{jobId:data.id,userId,topic},{jobId:data.id,attempts:3,backoff:{type:"exponential",delay:30000},removeOnComplete:100,removeOnFail:200});
}
async function processJob(job:Job):Promise<void>{
 if(job.name==="daily-autopilot"){const userId=String(job.data.userId||"");if(userId)await createDailyJob(userId);return;}
 if(job.name==="produce-video"){await runProduction({db,jobId:String(job.data.jobId),userId:String(job.data.userId),topic:String(job.data.topic)});return;}
 throw new Error("Unsupported worker job type");
}
const worker=new Worker("youtube-production",processJob,{connection,concurrency:Number(process.env.WORKER_CONCURRENCY||1),limiter:{max:3,duration:60000}});
worker.on("completed",job=>console.info("youtube production job completed",job.id,job.name));
worker.on("failed",(job,error)=>console.error("youtube production job failed",job?.id,job?.name,error.message.slice(0,300)));
console.info("YouTube production worker started");
const heartbeat=setInterval(()=>{void connection.set("youtube-worker:heartbeat",new Date().toISOString(),"EX",60).catch(()=>undefined)},20000);
void connection.set("youtube-worker:heartbeat",new Date().toISOString(),"EX",60).catch(()=>undefined);
async function shutdown(){clearInterval(heartbeat);await worker.close();await queue.close();await connection.quit();process.exit(0);}
process.on("SIGTERM",shutdown);process.on("SIGINT",shutdown);