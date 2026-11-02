import {test} from "node:test";
import assert from "node:assert/strict";
import {scheduledVideoStatus} from "./youtube.js";
import {decryptSecret,encryptSecret} from "./security.js";

process.env.TOKEN_ENCRYPTION_KEY=Buffer.alloc(32,7).toString("hex");
process.env.OAUTH_STATE_SECRET="test-only-state-secret-with-more-than-32-characters";

test("encrypts OAuth secrets with authenticated encryption and round-trips",()=>{
 const original="refresh-token-test-value";
 const encrypted=encryptSecret(original);
 assert.notEqual(encrypted,original);
 assert.equal(decryptSecret(encrypted),original);
});

test("scheduled publishing always uses private privacy and a future timestamp",()=>{
 const publishAt=new Date(Date.now()+60*60*1000).toISOString();
 const status=scheduledVideoStatus({publishAt,madeForKids:false,containsSyntheticMedia:true});
 assert.equal(status.privacyStatus,"private");
 assert.equal(status.publishAt,publishAt);
 assert.equal(status.selfDeclaredMadeForKids,false);
 assert.equal(status.containsSyntheticMedia,true);
});

test("rejects a past YouTube publish time",()=>{
 assert.throws(()=>scheduledVideoStatus({publishAt:new Date(Date.now()-10000).toISOString()}),/future/);
});

test("does not guess audience or synthetic declarations",()=>{
 const status=scheduledVideoStatus({publishAt:new Date(Date.now()+600000).toISOString()});
 assert.equal(status.selfDeclaredMadeForKids,undefined);
 assert.equal(status.containsSyntheticMedia,undefined);
});