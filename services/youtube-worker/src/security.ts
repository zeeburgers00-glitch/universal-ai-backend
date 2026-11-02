import {createDecipheriv} from "node:crypto";
export function decryptSecret(value:string):string{
 const raw=process.env.TOKEN_ENCRYPTION_KEY||"";
 const key=/^[0-9a-fA-F]{64}$/.test(raw)?Buffer.from(raw,"hex"):Buffer.from(raw,"base64");
 if(key.length!==32)throw new Error("TOKEN_ENCRYPTION_KEY must encode exactly 32 bytes");
 const parts=value.split(".");
 if(parts.length!==3)throw new Error("Encrypted OAuth credential is malformed");
 const decipher=createDecipheriv("aes-256-gcm",key,Buffer.from(parts[0],"base64url"));
 decipher.setAuthTag(Buffer.from(parts[1],"base64url"));
 return Buffer.concat([decipher.update(Buffer.from(parts[2],"base64url")),decipher.final()]).toString("utf8");
}