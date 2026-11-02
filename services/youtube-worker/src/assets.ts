import {promisify} from "node:util";
import {execFile as execFileCallback} from "node:child_process";
import {promises as fs} from "node:fs";
import path from "node:path";
import type {ScriptPack} from "./model.js";

const execFile=promisify(execFileCallback);
function setting(name:string):string{const v=process.env[name];if(!v)throw new Error("Missing media provider setting: "+name);return v;}
async function command(file:string,args:string[],timeout=180000):Promise<string>{
 const result=await execFile(file,args,{timeout,maxBuffer:10*1024*1024});
 return result.stdout;
}
function chunks(text:string,max=4200):string[]{
 const paragraphs=text.split(/\n{2,}/).filter(Boolean),out:string[]=[];let current="";
 for(const paragraph of paragraphs){
  if(paragraph.length>max){if(current){out.push(current);current=""}for(let i=0;i<paragraph.length;i+=max)out.push(paragraph.slice(i,i+max));continue}
  if((current+"\n\n"+paragraph).length>max&&current){out.push(current);current=paragraph}else current=current?current+"\n\n"+paragraph:paragraph;
 }
 if(current)out.push(current);
 return out;
}
async function getPexelsClip(query:string,dir:string,index:number):Promise<{path:string;video_id:number;page_url:string;creator:string;license:string}>{
 const response=await fetch("https://api.pexels.com/videos/search?query="+encodeURIComponent(query)+"&orientation=landscape&size=large&per_page=5",{headers:{Authorization:setting("PEXELS_API_KEY")}});
 if(!response.ok)throw new Error("Pexels video search returned HTTP "+response.status);
 const result=await response.json() as {videos?:{id:number;url:string;user?:{name?:string};video_files?:{link:string;width?:number;file_type?:string}[]}[]};
 const video=(result.videos||[]).find(v=>(v.video_files||[]).some(f=>f.link&&f.file_type==="video/mp4"));
 if(!video)throw new Error("Pexels returned no MP4 stock video for scene: "+query.slice(0,90));
 const selected=(video.video_files||[]).filter(f=>f.link&&f.file_type==="video/mp4").sort((a,b)=>(b.width||0)-(a.width||0))[0];
 const download=await fetch(selected.link);
 if(!download.ok)throw new Error("Could not download a selected Pexels video asset");
 const bytes=Buffer.from(await download.arrayBuffer());
 if(bytes.length<50000||bytes.length>400000000)throw new Error("Pexels video download exceeded safety limits");
 const source=path.join(dir,"pexels-"+index+".mp4"),clip=path.join(dir,"scene-"+index+".mp4");
 await fs.writeFile(source,bytes);
 await command(process.env.FFMPEG_PATH||"ffmpeg",["-y","-stream_loop","-1","-i",source,"-t","20","-vf","scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,eq=contrast=1.03:saturation=1.08,format=yuv420p","-an","-c:v","libx264","-preset","veryfast","-crf","23",clip],180000);
 return {path:clip,video_id:video.id,page_url:video.url,creator:video.user?.name||"Unknown creator",license:"Pexels license"};
}
async function makeVoice(script:string,dir:string):Promise<string>{
 const apiKey=setting("ELEVENLABS_API_KEY"),voiceId=setting("ELEVENLABS_VOICE_ID"),parts=chunks(script),paths:string[]=[];
 for(let i=0;i<parts.length;i++){
  const response=await fetch("https://api.elevenlabs.io/v1/text-to-speech/"+encodeURIComponent(voiceId)+"?output_format=mp3_44100_128",{
   method:"POST",headers:{"xi-api-key":apiKey,"Content-Type":"application/json","Accept":"audio/mpeg"},
   body:JSON.stringify({text:parts[i],model_id:"eleven_multilingual_v2",voice_settings:{stability:0.55,similarity_boost:0.75,speed:0.98}})
  });
  if(!response.ok)throw new Error("Voice generation provider returned HTTP "+response.status);
  const p=path.join(dir,"voice-"+String(i).padStart(3,"0")+".mp3");
  await fs.writeFile(p,Buffer.from(await response.arrayBuffer()));paths.push(p);
 }
 const list=path.join(dir,"audio-list.txt");
 await fs.writeFile(list,paths.map(p=>"file '"+p.replace(/'/g,"'\\''")+"'").join("\n"));
 const output=path.join(dir,"narration.mp3");
 await command(process.env.FFMPEG_PATH||"ffmpeg",["-y","-f","concat","-safe","0","-i",list,"-c","copy",output],120000);
 return output;
}
async function makeCaptions(audio:string,dir:string):Promise<string>{
 const form=new FormData(),buffer=await fs.readFile(audio);
 form.append("model","whisper-1");form.append("response_format","srt");
 form.append("file",new Blob([buffer],{type:"audio/mpeg"}),"narration.mp3");
 const response=await fetch("https://api.openai.com/v1/audio/transcriptions",{method:"POST",headers:{Authorization:"Bearer "+setting("OPENAI_API_KEY")},body:form});
 if(!response.ok)throw new Error("Whisper transcription returned HTTP "+response.status);
 const result=await response.text();
 if(!result.includes("-->")||result.length<100)throw new Error("Whisper did not return a valid SRT caption track");
 const file=path.join(dir,"captions.srt");await fs.writeFile(file,result,"utf8");return file;
}
export type RenderedAssets={video:string;captions:string;thumbnail:string;duration:number;assets:{video_id:number;page_url:string;creator:string;license:string}[]};
export async function renderVideo(pack:ScriptPack,dir:string):Promise<RenderedAssets>{
 const assets=[];
 for(let i=0;i<pack.scenes.length;i++)assets.push(await getPexelsClip(pack.scenes[i].query,dir,i));
 if(assets.length<8)throw new Error("Not enough distinct Pexels stock clips for a safe render");
 const concat=path.join(dir,"visual-list.txt");
 await fs.writeFile(concat,assets.map(a=>"file '"+a.path+"'").join("\n"));
 const visuals=path.join(dir,"visuals.mp4");
 await command(process.env.FFMPEG_PATH||"ffmpeg",["-y","-f","concat","-safe","0","-i",concat,"-c","copy",visuals],180000);
 const voice=await makeVoice(pack.script,dir);
 const captions=await makeCaptions(voice,dir);
 const video=path.join(dir,"final.mp4");
 const filter="subtitles='"+captions.replace(/:/g,"\\:").replace(/'/g,"\\'")+"':force_style='FontName=DejaVu Sans,FontSize=22,Outline=2,Shadow=1,MarginV=32'";
 await command(process.env.FFMPEG_PATH||"ffmpeg",["-y","-stream_loop","-1","-i",visuals,"-i",voice,"-map","0:v:0","-map","1:a:0","-vf",filter,"-shortest","-c:v","libx264","-preset","veryfast","-crf","21","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",video],1200000);
 const probe=await command(process.env.FFPROBE_PATH||"ffprobe",["-v","error","-show_entries","format=duration:stream=width,height,codec_type","-of","json",video],30000);
 const details=JSON.parse(probe) as {format?:{duration?:string};streams?:{width?:number;height?:number;codec_type?:string}[]};
 const duration=Number(details.format?.duration||0),stream=(details.streams||[]).find(x=>x.codec_type==="video");
 const min=Number(process.env.MIN_VIDEO_DURATION_SECONDS||600),max=Number(process.env.MAX_VIDEO_DURATION_SECONDS||900);
 if(duration<min||duration>max)throw new Error("Rendered duration is outside the configured 10–15 minute quality range");
 if((stream?.width||0)<1920||(stream?.height||0)<1080)throw new Error("Rendered video did not pass the 1080p resolution gate");
 const thumbnail=path.join(dir,"thumbnail.jpg");
 await command(process.env.FFMPEG_PATH||"ffmpeg",["-y","-ss","00:00:20","-i",video,"-frames:v","1","-vf","scale=1280:720","-q:v","2",thumbnail],30000);
 return {video,captions,thumbnail,duration,assets:assets.map(a=>({video_id:a.video_id,page_url:a.page_url,creator:a.creator,license:a.license}))};
}