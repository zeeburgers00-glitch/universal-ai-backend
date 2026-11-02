import { google,youtube_v3 } from "googleapis";
import { createReadStream } from "node:fs";
import { decryptSecret,encryptSecret } from "./security.js";

export const YOUTUBE_SCOPES=[
  "https://www.googleapis.com/auth/youtube.readonly",
  "https://www.googleapis.com/auth/youtube.upload"
];
export function oauthClient():InstanceType<typeof google.auth.OAuth2>{
  const id=process.env.GOOGLE_CLIENT_ID,secret=process.env.GOOGLE_CLIENT_SECRET,redirect=process.env.GOOGLE_REDIRECT_URI;
  if(!id||!secret||!redirect)throw new Error("Google OAuth client ID, secret and callback URL must be configured");
  return new google.auth.OAuth2(id,secret,redirect);
}
export function scheduledVideoStatus(input:{publishAt:string;madeForKids?:boolean|null;containsSyntheticMedia?:boolean}):youtube_v3.Schema$VideoStatus{
  const timestamp=Date.parse(input.publishAt);
  if(!Number.isFinite(timestamp)||timestamp<Date.now()+120000)throw new Error("publishAt must be a valid time at least two minutes in the future");
  const result:youtube_v3.Schema$VideoStatus={privacyStatus:"private",publishAt:new Date(timestamp).toISOString()};
  if(typeof input.madeForKids==="boolean")result.selfDeclaredMadeForKids=input.madeForKids;
  if(typeof input.containsSyntheticMedia==="boolean")result.containsSyntheticMedia=input.containsSyntheticMedia;
  return result;
}
export async function uploadScheduledVideo(args:{
  accessToken:string;refreshToken:string;filePath:string;publishAt:string;title:string;description:string;tags:string[];categoryId:string;
  madeForKids?:boolean|null;containsSyntheticMedia?:boolean;
}):Promise<{videoId:string;url:string}>{
  const auth=oauthClient();
  auth.setCredentials({access_token:args.accessToken,refresh_token:args.refreshToken});
  const yt=google.youtube({version:"v3",auth});
  const response=await yt.videos.insert({
    part:["snippet","status"],
    requestBody:{
      snippet:{title:args.title.slice(0,100),description:args.description.slice(0,5000),tags:args.tags.slice(0,30),categoryId:args.categoryId},
      status:scheduledVideoStatus({publishAt:args.publishAt,madeForKids:args.madeForKids,containsSyntheticMedia:args.containsSyntheticMedia})
    },
    media:{body:createReadStream(args.filePath)}
  },{onUploadProgress:event=>{void event}});
  const videoId=response.data.id;
  if(!videoId)throw new Error("YouTube did not return a video ID after upload");
  return {videoId,url:"https://www.youtube.com/watch?v="+videoId};
}
export function encryptedTokenPair(tokens:{access_token?:string|null;refresh_token?:string|null}):{access_token_enc:string|null;refresh_token_enc:string|null}{
  return {access_token_enc:tokens.access_token?encryptSecret(tokens.access_token):null,refresh_token_enc:tokens.refresh_token?encryptSecret(tokens.refresh_token):null};
}
export function revealRefreshToken(encrypted:string):string{return decryptSecret(encrypted);}