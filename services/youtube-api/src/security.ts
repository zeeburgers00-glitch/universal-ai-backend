import { createCipheriv,createDecipheriv,createHmac,randomBytes,timingSafeEqual } from "node:crypto";
type RedisStateStore = { set(key:string,value:string,...args:(string|number)[]):Promise<unknown>; eval(script:string,numKeys:number,...args:(string|number)[]):Promise<unknown>; };

function encryptionKey():Buffer {
  const raw=process.env.TOKEN_ENCRYPTION_KEY||"";
  const key=/^[0-9a-fA-F]{64}$/.test(raw)?Buffer.from(raw,"hex"):Buffer.from(raw,"base64");
  if(key.length!==32)throw new Error("TOKEN_ENCRYPTION_KEY must encode exactly 32 bytes");
  return key;
}
function stateSecret():string {
  const secret=process.env.OAUTH_STATE_SECRET||"";
  if(secret.length<32)throw new Error("OAUTH_STATE_SECRET must contain at least 32 characters");
  return secret;
}
export function encryptSecret(value:string):string {
  const iv=randomBytes(12),cipher=createCipheriv("aes-256-gcm",encryptionKey(),iv);
  const encrypted=Buffer.concat([cipher.update(value,"utf8"),cipher.final()]);
  return [iv.toString("base64url"),cipher.getAuthTag().toString("base64url"),encrypted.toString("base64url")].join(".");
}
export function decryptSecret(value:string):string {
  const parts=value.split(".");
  if(parts.length!==3)throw new Error("Encrypted credential has an invalid format");
  const decipher=createDecipheriv("aes-256-gcm",encryptionKey(),Buffer.from(parts[0],"base64url"));
  decipher.setAuthTag(Buffer.from(parts[1],"base64url"));
  return Buffer.concat([decipher.update(Buffer.from(parts[2],"base64url")),decipher.final()]).toString("utf8");
}
type StatePayload={userId:string;nonce:string;expiresAt:number};
export async function createOAuthState(userId:string,redis:RedisStateStore):Promise<string>{
  const nonce=randomBytes(24).toString("base64url");
  const payload:StatePayload={userId,nonce,expiresAt:Date.now()+10*60*1000};
  await redis.set("yt-oauth-state:"+nonce,userId,"EX",600,"NX");
  const encoded=Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature=createHmac("sha256",stateSecret()).update(encoded).digest("base64url");
  return encoded+"."+signature;
}
export async function consumeOAuthState(state:string,redis:Redis):Promise<string>{
  const [encoded,signature,...extra]=state.split(".");
  if(!encoded||!signature||extra.length)throw new Error("Invalid OAuth state");
  const expected=createHmac("sha256",stateSecret()).update(encoded).digest();
  const supplied=Buffer.from(signature,"base64url");
  if(supplied.length!==expected.length||!timingSafeEqual(supplied,expected))throw new Error("Invalid OAuth state signature");
  const payload=JSON.parse(Buffer.from(encoded,"base64url").toString("utf8")) as StatePayload;
  if(!payload.userId||!payload.nonce||payload.expiresAt<Date.now())throw new Error("OAuth state expired");
  const key="yt-oauth-state:"+payload.nonce;
  const stored=await redis.eval("local v=redis.call('GET',KEYS[1]); if v then redis.call('DEL',KEYS[1]); end; return v",1,key) as string|null;
  if(stored!==payload.userId)throw new Error("OAuth state was already used or is invalid");
  return payload.userId;
}