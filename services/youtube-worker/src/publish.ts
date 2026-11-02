import {google} from "googleapis";
import {createReadStream} from "node:fs";
import {fromZonedTime} from "date-fns-tz";
import {decryptSecret} from "./security.js";
import type {ScriptPack} from "./model.js";

function required(name:string):string{const value=process.env[name];if(!value)throw new Error("Missing YouTube publishing setting: "+name);return value;}
function scheduledTime(time:string,timezone:string):string{
 const parts=time.split(":").map(Number),now=new Date();
 const localDate=new Intl.DateTimeFormat("en-CA",{timeZone:timezone,year:"numeric",month:"2-digit",day:"2-digit"}).format(now);
 const clock=String(parts[0]).padStart(2,"0")+":"+String(parts[1]).padStart(2,"0")+":00";
 let date=fromZonedTime(localDate+"T"+clock,timezone);
 if(date.getTime()<now.getTime()+20*60*1000){
  const p=localDate.split("-").map(Number),tomorrow=new Date(Date.UTC(p[0],p[1]-1,p[2]+1));
  const nextDate=tomorrow.getUTCFullYear()+"-"+String(tomorrow.getUTCMonth()+1).padStart(2,"0")+"-"+String(tomorrow.getUTCDate()).padStart(2,"0");
  date=fromZonedTime(nextDate+"T"+clock,timezone);
 }
 if(date.getTime()<now.getTime()+120000)throw new Error("A future YouTube publish time could not be calculated");
 return date.toISOString();
}
export async function publishPrivateScheduled(args:{
 db:any;userId:string;filePath:string;thumbnailPath:string;pack:ScriptPack;settings:Record<string,unknown>;
}):Promise<{videoId:string;url:string;publishAt:string}>{
 const {data:row,error}=await args.db.from("youtube_connections").select("channel_id,refresh_token_enc").eq("user_id",args.userId).maybeSingle();
 if(error||!row?.refresh_token_enc)throw new Error("Connected YouTube channel is missing or disconnected");
 const publishAt=scheduledTime(String(args.settings.schedule_time||"18:00"),String(args.settings.timezone||"Asia/Karachi"));
 const auth=new google.auth.OAuth2(required("GOOGLE_CLIENT_ID"),required("GOOGLE_CLIENT_SECRET"),required("GOOGLE_REDIRECT_URI"));
 auth.setCredentials({refresh_token:decryptSecret(row.refresh_token_enc)});
 const {token}=await auth.getAccessToken();
 if(!token)throw new Error("Google OAuth could not refresh the YouTube access token");
 const yt=google.youtube({version:"v3",auth});
 const upload=await yt.videos.insert({
  part:["snippet","status"],
  requestBody:{
   snippet:{title:args.pack.title.slice(0,100),description:args.pack.description.slice(0,4900),tags:args.pack.tags.slice(0,30),categoryId:process.env.YOUTUBE_CATEGORY_ID||"27"},
   status:{
    privacyStatus:"private",
    publishAt,
    selfDeclaredMadeForKids:args.settings.made_for_kids as boolean,
    containsSyntheticMedia:args.settings.contains_synthetic_media as boolean
   }
  },
  media:{body:createReadStream(args.filePath)}
 });
 const videoId=upload.data.id;
 if(!videoId)throw new Error("YouTube returned no video ID after the upload request");
 await yt.thumbnails.set({videoId,media:{body:createReadStream(args.thumbnailPath)}});
 return {videoId,url:"https://www.youtube.com/watch?v="+videoId,publishAt};
}