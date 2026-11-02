import "dotenv/config";
import Fastify,{FastifyRequest,FastifyReply} from "fastify";
import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import rateLimit from "@fastify/rate-limit";
import {createClient} from "@supabase/supabase-js";
import Redis from "ioredis";
import {Queue} from "bullmq";
import {google} from "googleapis";
import {z} from "zod";
import {consumeOAuthState,createOAuthState,encryptSecret,decryptSecret,RedisStateStore} from "./security.js";
import {oauthClient,YOUTUBE_SCOPES} from "./youtube.js";

const app=Fastify({logger:{level:process.env.LOG_LEVEL||"info",redact:{paths:["req.headers.authorization","req.headers.cookie"],censor:"[REDACTED]"}}});
const supabaseUrl=process.env.SUPABASE_URL||"";
const serviceKey=process.env.SUPABASE_SERVICE_ROLE_KEY||"";
const db=supabaseUrl&&serviceKey?createClient(supabaseUrl,serviceKey,{auth:{persistSession:false,autoRefreshToken:false}}):null;
const redis=process.env.REDIS_URL?new Redis(process.env.REDIS_URL,{maxRetriesPerRequest:null,enableReadyCheck:true}):null;
const queue=redis?new Queue("youtube-production",{connection:redis}):null;
type UserRequest=FastifyRequest&{userId?:string};
async function requireUser(req:FastifyRequest,reply:FastifyReply){
  const token=(req.headers.authorization||"").replace(/^Bearer\s+/i,"");
  if(!token||!db){reply.code(401).send({message:"Sign in with Supabase Auth first."});return;}
  const {data,error}=await db.auth.getUser(token);
  if(error||!data.user){reply.code(401).send({message:"Your sign-in session is invalid or expired."});return;}
  (req as UserRequest).userId=data.user.id;
}
function uid(req:FastifyRequest):string{return (req as UserRequest).userId||"";}
function requireDb(){if(!db)throw new Error("Supabase service configuration is missing");return db;}
function requireQueue(){if(!queue)throw new Error("Redis queue is not configured");return queue;}
const settingsSchema=z.object({
  niche:z.string().min(2).max(160).optional(),
  language:z.string().min(2).max(40).optional(),
  target_audience:z.string().min(2).max(180).optional(),
  schedule_time:z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/).optional(),
  timezone:z.string().min(3).max(80).optional(),
  daily_budget_usd:z.number().min(0).max(10000).optional(),
  made_for_kids:z.boolean().nullable().optional(),
  contains_synthetic_media:z.boolean().nullable().optional()
}).strict();
const jobSchema=z.object({topic:z.string().min(8).max(300)}).strict();
function cronFor(time:string):string{const [hour,minute]=time.split(":");return minute+" "+hour+" * * *";}
function webUrl(path:string):string{return (process.env.WEB_APP_URL||"https://localhost:3000").replace(/\/$/,"")+path;}

await app.register(helmet,{contentSecurityPolicy:false});
await app.register(cors,{origin:(process.env.CORS_ORIGINS||"").split(",").map(x=>x.trim()).filter(Boolean),credentials:false});
await app.register(rateLimit,{max:120,timeWindow:"1 minute"});
app.get("/v1/health",async(_req,reply)=>{
  const checks={database:false,redis:false};
  if(db){const {error}=await db.from("creator_settings").select("user_id").limit(1);checks.database=!error;}
  if(redis){try{checks.redis=(await redis.ping())==="PONG"}catch{checks.redis=false}}
  return reply.code(checks.database?200:503).send({status:checks.database?"ok":"degraded",service:"youtube-autopilot-api",checks});
});
app.post("/v1/youtube/oauth/start",{preHandler:requireUser},async(req,reply)=>{
  if(!redis)return reply.code(503).send({message:"OAuth state store is not configured; Redis is required."});
  try{
    const state=await createOAuthState(uid(req),redis as unknown as RedisStateStore);
    const url=oauthClient().generateAuthUrl({access_type:"offline",include_granted_scopes:true,prompt:"consent",scope:YOUTUBE_SCOPES,state});
    return {authorization_url:url,scopes:YOUTUBE_SCOPES};
  }catch(e){return reply.code(503).send({message:e instanceof Error?e.message:"OAuth is not configured"})}
});
app.get("/v1/youtube/oauth/callback",async(req,reply)=>{
  const query=req.query as {state?:string;code?:string;error?:string};
  if(query.error)return reply.redirect(webUrl("/?youtube=denied"));
  if(!query.state||!query.code||!redis||!db)return reply.code(400).send({message:"OAuth callback is missing required state, code, or backend configuration."});
  try{
    const userId=await consumeOAuthState(query.state,redis as unknown as RedisStateStore);
    const client=oauthClient();
    const {tokens}=await client.getToken(query.code);
    client.setCredentials(tokens);
    const yt=google.youtube({version:"v3",auth:client});
    const channels=await yt.channels.list({part:["snippet","id"],mine:true,maxResults:1});
    const channel=channels.data.items?.[0];
    if(!channel?.id)return reply.redirect(webUrl("/?youtube=channel_missing"));
    const {data:previous}=await db.from("youtube_connections").select("refresh_token_enc").eq("user_id",userId).maybeSingle();
    const refresh=tokens.refresh_token?encryptSecret(tokens.refresh_token):previous?.refresh_token_enc;
    if(!refresh)throw new Error("Google did not return a refresh token. Reconnect and grant offline access.");
    const {error}=await db.from("youtube_connections").upsert({
      user_id:userId,channel_id:channel.id,channel_title:channel.snippet?.title||"YouTube channel",
      channel_thumbnail:channel.snippet?.thumbnails?.default?.url||null,
      access_token_enc:tokens.access_token?encryptSecret(tokens.access_token):null,
      refresh_token_enc:refresh,expires_at:tokens.expiry_date?new Date(tokens.expiry_date).toISOString():null,
      scopes:YOUTUBE_SCOPES,updated_at:new Date().toISOString()
    },{onConflict:"user_id"});
    if(error)throw new Error("Could not securely save the YouTube connection");
    return reply.redirect(webUrl("/?youtube=connected"));
  }catch(e){req.log.warn({err:e},"YouTube OAuth callback rejected");return reply.redirect(webUrl("/?youtube=error"))}
});
app.get("/v1/youtube/connection",{preHandler:requireUser},async(req)=>{
  const {data,error}=await requireDb().from("youtube_connections").select("channel_id,channel_title,channel_thumbnail,updated_at,scopes").eq("user_id",uid(req)).maybeSingle();
  if(error)throw error;
  return {connected:Boolean(data),channel:data?{id:data.channel_id,title:data.channel_title,thumbnail:data.channel_thumbnail}:null,updated_at:data?.updated_at||null,scopes:data?.scopes||[]};
});
app.delete("/v1/youtube/connection",{preHandler:requireUser},async(req,reply)=>{
  const clientDb=requireDb(),userId=uid(req);
  const {data}=await clientDb.from("youtube_connections").select("refresh_token_enc").eq("user_id",userId).maybeSingle();
  if(data?.refresh_token_enc){try{const token=decryptSecret(data.refresh_token_enc);await fetch("https://oauth2.googleapis.com/revoke",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({token})})}catch{req.log.warn("Google revoke request failed; local token deletion will continue")}}
  const {error}=await clientDb.from("youtube_connections").delete().eq("user_id",userId);
  if(error)return reply.code(500).send({message:"Could not remove the YouTube connection"});
  return {disconnected:true};
});
app.get("/v1/settings",{preHandler:requireUser},async(req)=>{
  const {data,error}=await requireDb().from("creator_settings").select("*").eq("user_id",uid(req)).maybeSingle();
  if(error)throw error;
  return {settings:data||{niche:"",language:"English",target_audience:"",schedule_time:"18:00",timezone:"Asia/Karachi",daily_budget_usd:0,autopublish_enabled:false}};
});
app.put("/v1/settings",{preHandler:requireUser},async(req,reply)=>{
  const parsed=settingsSchema.safeParse(req.body);
  if(!parsed.success)return reply.code(400).send({message:"Invalid settings",issues:parsed.error.issues});
  const {data,error}=await requireDb().from("creator_settings").upsert({user_id:uid(req),...parsed.data,updated_at:new Date().toISOString()},{onConflict:"user_id"}).select("*").single();
  if(error)throw error;
  return {settings:data};
});
app.get("/v1/dashboard",{preHandler:requireUser},async(req)=>{
  const clientDb=requireDb(),userId=uid(req);
  const [conn,settings,jobs,usage]=await Promise.all([
    clientDb.from("youtube_connections").select("channel_id,channel_title,channel_thumbnail").eq("user_id",userId).maybeSingle(),
    clientDb.from("creator_settings").select("*").eq("user_id",userId).maybeSingle(),
    clientDb.from("production_jobs").select("id,topic,status,stage,progress,created_at,error,output").eq("user_id",userId).order("created_at",{ascending:false}).limit(20),
    clientDb.from("provider_usage").select("cost_usd,created_at").eq("user_id",userId).gte("created_at",new Date(Date.now()-24*60*60*1000).toISOString())
  ]);
  if(conn.error||settings.error||jobs.error||usage.error)throw new Error("Could not load dashboard data");
  const spent=(usage.data||[]).reduce((sum,row)=>sum+Number(row.cost_usd||0),0);
  return {channel:conn.data?{id:conn.data.channel_id,title:conn.data.channel_title,thumbnail:conn.data.channel_thumbnail}:null,settings:settings.data||{},jobs:jobs.data||[],usage:{today_usd:Number(spent.toFixed(4))}};
});
app.post("/v1/jobs",{preHandler:requireUser},async(req,reply)=>{
  const parsed=jobSchema.safeParse(req.body);
  if(!parsed.success)return reply.code(400).send({message:"A specific topic is required",issues:parsed.error.issues});
  const idem=String(req.headers["idempotency-key"]||"").slice(0,120);
  if(!idem)return reply.code(400).send({message:"Idempotency-Key header is required"});
  try{
    const clientDb=requireDb(),jobsQueue=requireQueue(),userId=uid(req);
    const {data:existing}=await clientDb.from("production_jobs").select("id,status").eq("user_id",userId).eq("idempotency_key",idem).maybeSingle();
    if(existing)return reply.code(200).send({job_id:existing.id,status:existing.status,reused:true});
    const {data,error}=await clientDb.from("production_jobs").insert({user_id:userId,topic:parsed.data.topic,idempotency_key:idem,status:"queued",stage:"queued",progress:0}).select("id").single();
    if(error)throw error;
    await jobsQueue.add("produce-video",{jobId:data.id,userId,topic:parsed.data.topic},{jobId:data.id,attempts:3,backoff:{type:"exponential",delay:30000},removeOnComplete:100,removeOnFail:200});
    return reply.code(202).send({job_id:data.id,status:"queued"});
  }catch(e){req.log.error({err:e},"Could not queue production job");return reply.code(503).send({message:e instanceof Error?e.message:"Production queue unavailable"})}
});
app.post("/v1/automation/enable",{preHandler:requireUser},async(req,reply)=>{
  const clientDb=requireDb(),jobsQueue=requireQueue(),userId=uid(req);
  const {data:connection}=await clientDb.from("youtube_connections").select("channel_id").eq("user_id",userId).maybeSingle();
  const {data:settings}=await clientDb.from("creator_settings").select("*").eq("user_id",userId).maybeSingle();
  const required=["MODEL_API_KEY","MODEL_NAME","TAVILY_API_KEY","PEXELS_API_KEY","ELEVENLABS_API_KEY","ELEVENLABS_VOICE_ID","OPENAI_API_KEY","GOOGLE_CLIENT_ID","GOOGLE_CLIENT_SECRET","GOOGLE_REDIRECT_URI"];
  const missing=required.filter(key=>!process.env[key]);
  if(!connection?.channel_id)missing.unshift("YouTube OAuth channel connection");
  if(!settings||Number(settings.daily_budget_usd)<=0)missing.push("daily budget greater than zero");
  if(typeof settings?.made_for_kids!=="boolean")missing.push("explicit Made for Kids audience declaration");
  if(typeof settings?.contains_synthetic_media!=="boolean")missing.push("explicit altered/synthetic media declaration");
  if(missing.length)return reply.code(409).send({message:"Autopublish prerequisites are not ready.",missing});
  const time=settings.schedule_time||"18:00",timezone=settings.timezone||"Asia/Karachi";
  await jobsQueue.upsertJobScheduler("daily-autopilot:"+userId,{pattern:cronFor(time),tz:timezone},{name:"daily-autopilot",data:{userId},opts:{removeOnComplete:100,removeOnFail:100}});
  const {error}=await clientDb.from("creator_settings").upsert({user_id:userId,autopublish_enabled:true,updated_at:new Date().toISOString()},{onConflict:"user_id"});
  if(error)throw error;
  return {enabled:true,schedule:{time,timezone,frequency:"daily"}};
});
app.post("/v1/automation/disable",{preHandler:requireUser},async(req)=>{
  const jobsQueue=requireQueue(),userId=uid(req);
  await jobsQueue.removeJobScheduler("daily-autopilot:"+userId);
  const {error}=await requireDb().from("creator_settings").upsert({user_id:userId,autopublish_enabled:false,updated_at:new Date().toISOString()},{onConflict:"user_id"});
  if(error)throw error;
  return {enabled:false};
});
app.post("/v1/automation/stop-all",{preHandler:requireUser},async(req)=>{
  const jobsQueue=requireQueue(),userId=uid(req);
  await jobsQueue.removeJobScheduler("daily-autopilot:"+userId);
  const clientDb=requireDb();
  await clientDb.from("creator_settings").upsert({user_id:userId,autopublish_enabled:false,updated_at:new Date().toISOString()},{onConflict:"user_id"});
  await clientDb.from("production_jobs").update({status:"cancelled",stage:"stopped_by_user",updated_at:new Date().toISOString()}).eq("user_id",userId).in("status",["queued","running"]);
  return {stopped:true};
});

app.setErrorHandler((error,req,reply)=>{
  req.log.error({err:error},"Request failed");
  const status=error.statusCode&&error.statusCode>=400?error.statusCode:500;
  reply.code(status).send({message:status>=500?"The request could not be completed. Check service logs for the redacted error.":error.message});
});
const port=Number(process.env.PORT||8080);
try{await app.listen({host:"0.0.0.0",port})}catch(error){app.log.error(error);process.exit(1)}
process.on("SIGTERM",async()=>{await queue?.close();await redis?.quit();await app.close();process.exit(0)});
process.on("SIGINT",async()=>{await queue?.close();await redis?.quit();await app.close();process.exit(0)});