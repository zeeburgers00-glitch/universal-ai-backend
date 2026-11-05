# GitHub Tool Registry — 196 verified repos

Snapshot: `2026-11-05T10:36:13+00:00` · source: GitHub REST API · refresh with `python scripts/fetch_github_repos.py`

> **Honest note:** inhe repo me *vendor nahi* kiya gaya. Ye ek reviewed shortlist hai —
> stars/licence/language GitHub API se aaye hain, haath se nahi likhe. Har entry par
> `integration: reference-only` hai jab tak code sach me wire na ho.

## Endpoints

```bash
GET /v1/discover/github/registry/stats                         # totals + categories
GET /v1/discover/github/registry?category=mcp&min_stars=1000   # filter
GET /v1/discover/github/registry?q=whatsapp&limit=20           # text search
GET /v1/discover/github/registry/CopilotKit/OpenDots           # one repo
GET /v1/discover/github?category_preset=ai-agents              # live GitHub search
```

## Categories

| Category | Repos | Kahan map hota hai |
|---|---|---|
| `agents` | 23 | agent_worker |
| `agent-ui` | 7 | studio / frontend |
| `mcp` | 22 | rea_worker / tools catalog |
| `rag-bots` | 14 | automation_worker |
| `whatsapp` | 12 | channel_worker |
| `voice` | 12 | voice_worker |
| `tts` | 9 | voice_worker |
| `video` | 16 | media_worker / videoengine |
| `youtube` | 7 | youtube_worker |
| `workflow` | 10 | automation_worker |
| `inference` | 6 | deploy/modal + ai_router |
| `observability` | 8 | agent_worker |
| `image-gen` | 14 | media_worker / videoengine |
| `comfyui` | 12 | media_worker |
| `transcribe` | 12 | media_worker / voice_worker |
| `embeddings` | 3 | vault / rea_worker |
| `scraping` | 8 | rea_worker |
| `coding-agents` | 10 | agent_worker |
| `eval` | 8 | tests / control plane |

## Top picks per category

### agents

| Repo | Stars | Language | License |
|---|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers) | 312680 | Shell | MIT |
| [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | 149068 | Python | MIT |
| [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | 79216 | TypeScript | Apache-2.0 |
| [FoundationAgents/MetaGPT](https://github.com/FoundationAgents/MetaGPT) | 71183 | Python | MIT |
| [microsoft/autogen](https://github.com/microsoft/autogen) | 61710 | Python | CC-BY-4.0 |

### agent-ui

| Repo | Stars | Language | License |
|---|---|---|---|
| [iOfficeAI/AionUi](https://github.com/iOfficeAI/AionUi) | 34049 | TypeScript | Apache-2.0 |
| [GaiZhenbiao/ChuanhuChatGPT](https://github.com/GaiZhenbiao/ChuanhuChatGPT) | 15246 | Python | GPL-3.0 |
| [huggingface/chat-ui](https://github.com/huggingface/chat-ui) | 11021 | TypeScript | Apache-2.0 |
| [winfunc/deepreasoning](https://github.com/winfunc/deepreasoning) | 5352 | Rust | MIT |
| [DEEIX-AI/DEEIX-Chat](https://github.com/DEEIX-AI/DEEIX-Chat) | 1627 | Go | Apache-2.0 |

### mcp

| Repo | Stars | Language | License |
|---|---|---|---|
| [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | 97319 | - | MIT |
| [headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom) | 78893 | Python | Apache-2.0 |
| [zylon-ai/private-gpt](https://github.com/zylon-ai/private-gpt) | 57630 | Python | Apache-2.0 |
| [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | 39198 | TypeScript | Apache-2.0 |
| [DayuanJiang/next-ai-draw-io](https://github.com/DayuanJiang/next-ai-draw-io) | 36702 | TypeScript | Apache-2.0 |

### rag-bots

| Repo | Stars | Language | License |
|---|---|---|---|
| [The-Vibe-Company/quivr](https://github.com/The-Vibe-Company/quivr) | 39631 | Go | MIT |
| [chatchat-space/Langchain-Chatchat](https://github.com/chatchat-space/Langchain-Chatchat) | 38713 | Python | Apache-2.0 |
| [Tencent/WeKnora](https://github.com/Tencent/WeKnora) | 36557 | Go | NOASSERTION |
| [simstudioai/sim](https://github.com/simstudioai/sim) | 29989 | TypeScript | Apache-2.0 |
| [enescingoz/awesome-n8n-templates](https://github.com/enescingoz/awesome-n8n-templates) | 26277 | - | NOASSERTION |

### whatsapp

| Repo | Stars | Language | License |
|---|---|---|---|
| [wechaty/wechaty](https://github.com/wechaty/wechaty) | 23513 | TypeScript | Apache-2.0 |
| [wwebjs/whatsapp-web.js](https://github.com/wwebjs/whatsapp-web.js) | 22855 | JavaScript | Apache-2.0 |
| [rmyndharis/OpenWA](https://github.com/rmyndharis/OpenWA) | 16536 | TypeScript | MIT |
| [wangrongding/wechat-bot](https://github.com/wangrongding/wechat-bot) | 11526 | JavaScript | MIT |
| [mruniquehacker/Knightbot-MD](https://github.com/mruniquehacker/Knightbot-MD) | 8198 | JavaScript | ⚠️ none |

### voice

| Repo | Stars | Language | License |
|---|---|---|---|
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 21035 | Python | MIT |
| [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) | 17069 | Python | BSD-2-Clause |
| [livekit/agents](https://github.com/livekit/agents) | 15091 | Python | Apache-2.0 |
| [GetStream/Vision-Agents](https://github.com/GetStream/Vision-Agents) | 8201 | Python | Apache-2.0 |
| [Project-N-E-K-O/N.E.K.O](https://github.com/Project-N-E-K-O/N.E.K.O) | 3183 | Python | Apache-2.0 |

### tts

| Repo | Stars | Language | License |
|---|---|---|---|
| [coqui-ai/TTS](https://github.com/coqui-ai/TTS) | 46183 | Python | MPL-2.0 |
| [cjpais/Handy](https://github.com/cjpais/Handy) | 37584 | Rust | MIT |
| [index-tts/index-tts](https://github.com/index-tts/index-tts) | 24947 | Python | NOASSERTION |
| [Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | 21172 | Python | Apache-2.0 |
| [NVIDIA-NeMo/Speech](https://github.com/NVIDIA-NeMo/Speech) | 18700 | Python | Apache-2.0 |

### video

| Repo | Stars | Language | License |
|---|---|---|---|
| [huggingface/diffusers](https://github.com/huggingface/diffusers) | 34866 | Python | Apache-2.0 |
| [Anil-matcha/Open-Generative-AI](https://github.com/Anil-matcha/Open-Generative-AI) | 32327 | JavaScript | MIT |
| [HBAI-Ltd/Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) | 20670 | TypeScript | MIT |
| [duixcom/Duix-Avatar](https://github.com/duixcom/Duix-Avatar) | 16243 | C | NOASSERTION |
| [zai-org/CogVideo](https://github.com/zai-org/CogVideo) | 13184 | Python | Apache-2.0 |

### youtube

| Repo | Stars | Language | License |
|---|---|---|---|
| [rushindrasinha/youtube-shorts-pipeline](https://github.com/rushindrasinha/youtube-shorts-pipeline) | 2357 | Python | MIT |
| [naqashafzal/AI-Content-Studio](https://github.com/naqashafzal/AI-Content-Studio) | 903 | Python | NOASSERTION |
| [dragonwolfshovel/youtube-uploader](https://github.com/dragonwolfshovel/youtube-uploader) | 426 | Python | MIT |
| [wanghaisheng/easy-uploader](https://github.com/wanghaisheng/easy-uploader) | 386 | Python | MIT |
| [ChaitanyaEswarRajeshJakki/gemini-youtube-automation](https://github.com/ChaitanyaEswarRajeshJakki/gemini-youtube-automation) | 373 | Python | ⚠️ none |

### workflow

| Repo | Stars | Language | License |
|---|---|---|---|
| [n8n-io/n8n](https://github.com/n8n-io/n8n) | 209601 | TypeScript | NOASSERTION |
| [langgenius/dify](https://github.com/langgenius/dify) | 160447 | Python | NOASSERTION |
| [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 78804 | Python | ⚠️ none |
| [apache/airflow](https://github.com/apache/airflow) | 47369 | Python | Apache-2.0 |
| [kestra-io/kestra](https://github.com/kestra-io/kestra) | 30148 | Java | Apache-2.0 |

### inference

| Repo | Stars | Language | License |
|---|---|---|---|
| [jundot/omlx](https://github.com/jundot/omlx) | 23380 | Python | Apache-2.0 |
| [raullenchai/Rapid-MLX](https://github.com/raullenchai/Rapid-MLX) | 4102 | Python | NOASSERTION |
| [superlinked/sie](https://github.com/superlinked/sie) | 3476 | Python | Apache-2.0 |
| [Luce-Org/lucebox](https://github.com/Luce-Org/lucebox) | 2976 | C++ | Apache-2.0 |
| [ddalcu/mlx-serve](https://github.com/ddalcu/mlx-serve) | 2374 | Zig | NOASSERTION |

### observability

| Repo | Stars | Language | License |
|---|---|---|---|
| [raga-ai-hub/RagaAI-Catalyst](https://github.com/raga-ai-hub/RagaAI-Catalyst) | 16186 | Python | Apache-2.0 |
| [deepflowio/deepflow](https://github.com/deepflowio/deepflow) | 4316 | Go | Apache-2.0 |
| [future-agi/future-agi](https://github.com/future-agi/future-agi) | 2250 | Python | Apache-2.0 |
| [monoscope-tech/monoscope](https://github.com/monoscope-tech/monoscope) | 2043 | Haskell | AGPL-3.0 |
| [Scale3-Labs/langtrace](https://github.com/Scale3-Labs/langtrace) | 1233 | TypeScript | AGPL-3.0 |

### image-gen

| Repo | Stars | Language | License |
|---|---|---|---|
| [huggingface/diffusers](https://github.com/huggingface/diffusers) | 34866 | Python | Apache-2.0 |
| [Anil-matcha/Open-Generative-AI](https://github.com/Anil-matcha/Open-Generative-AI) | 32327 | JavaScript | MIT |
| [PicoTrex/Awesome-Nano-Banana-images](https://github.com/PicoTrex/Awesome-Nano-Banana-images) | 24008 | - | Apache-2.0 |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 21035 | Python | MIT |
| [HBAI-Ltd/Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) | 20670 | TypeScript | MIT |

### comfyui

| Repo | Stars | Language | License |
|---|---|---|---|
| [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) | 145137 | Python | GPL-3.0 |
| [ATH-MaaS/Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video) | 29782 | Python | Apache-2.0 |
| [Comfy-Org/ComfyUI-Manager](https://github.com/Comfy-Org/ComfyUI-Manager) | 16731 | Python | GPL-3.0 |
| [LykosAI/StabilityMatrix](https://github.com/LykosAI/StabilityMatrix) | 8987 | C# | AGPL-3.0 |
| [ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO](https://github.com/ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO) | 7955 | - | GPL-3.0 |

### transcribe

| Repo | Stars | Language | License |
|---|---|---|---|
| [openai/whisper](https://github.com/openai/whisper) | 111994 | Python | MIT |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | 25096 | Python | BSD-2-Clause |
| [Const-me/Whisper](https://github.com/Const-me/Whisper) | 10704 | C++ | MPL-2.0 |
| [liuzhao1225/YouDub-webui](https://github.com/liuzhao1225/YouDub-webui) | 5800 | TypeScript | Apache-2.0 |
| [MahmoudAshraf97/whisper-diarization](https://github.com/MahmoudAshraf97/whisper-diarization) | 5675 | Jupyter Notebook | BSD-2-Clause |

### embeddings

| Repo | Stars | Language | License |
|---|---|---|---|
| [codedogQBY/ReadAny](https://github.com/codedogQBY/ReadAny) | 2939 | TypeScript | NOASSERTION |
| [vearch/vearch](https://github.com/vearch/vearch) | 2333 | Python | Apache-2.0 |
| [pguso/rag-from-scratch](https://github.com/pguso/rag-from-scratch) | 1651 | JavaScript | MIT |

### scraping

| Repo | Stars | Language | License |
|---|---|---|---|
| [firecrawl/firecrawl](https://github.com/firecrawl/firecrawl) | 198785 | TypeScript | AGPL-3.0 |
| [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling) | 97221 | Python | BSD-3-Clause |
| [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) | 86930 | Python | Apache-2.0 |
| [scrapy/scrapy](https://github.com/scrapy/scrapy) | 65234 | Python | BSD-3-Clause |
| [apify/crawlee](https://github.com/apify/crawlee) | 26345 | TypeScript | Apache-2.0 |

### coding-agents

| Repo | Stars | Language | License |
|---|---|---|---|
| [earendil-works/pi](https://github.com/earendil-works/pi) | 120203 | TypeScript | MIT |
| [career-ops-hq/career-ops](https://github.com/career-ops-hq/career-ops) | 80308 | JavaScript | MIT |
| [cline/cline](https://github.com/cline/cline) | 71334 | TypeScript | Apache-2.0 |
| [sickn33/agentic-awesome-skills](https://github.com/sickn33/agentic-awesome-skills) | 49188 | Python | MIT |
| [herdrdev/herdr](https://github.com/herdrdev/herdr) | 48201 | Rust | Apache-2.0 |

### eval

| Repo | Stars | Language | License |
|---|---|---|---|
| [openai/evals](https://github.com/openai/evals) | 19708 | Python | NOASSERTION |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | 19312 | Python | Apache-2.0 |
| [raga-ai-hub/RagaAI-Catalyst](https://github.com/raga-ai-hub/RagaAI-Catalyst) | 16186 | Python | Apache-2.0 |
| [evidentlyai/evidently](https://github.com/evidentlyai/evidently) | 8042 | Jupyter Notebook | Apache-2.0 |
| [lm-sys/RouteLLM](https://github.com/lm-sys/RouteLLM) | 5676 | Python | Apache-2.0 |

## Bina licence wale repos (use se pehle check karo)

Total 11 — inka licence GitHub par nahi hai, matlab default copyright lagta hai:

| Repo | Stars |
|---|---|
| [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 78804 |
| [mruniquehacker/Knightbot-MD](https://github.com/mruniquehacker/Knightbot-MD) | 8198 |
| [showlab/Awesome-Video-Diffusion](https://github.com/showlab/Awesome-Video-Diffusion) | 5827 |
| [wide-trace/open-higgsfield](https://github.com/wide-trace/open-higgsfield) | 5378 |
| [askrella/whatsapp-chatgpt](https://github.com/askrella/whatsapp-chatgpt) | 3796 |
| [xenova/whisper-web](https://github.com/xenova/whisper-web) | 3345 |
| [google-gemini/gemini-live-api-examples](https://github.com/google-gemini/gemini-live-api-examples) | 574 |
| [ChaitanyaEswarRajeshJakki/gemini-youtube-automation](https://github.com/ChaitanyaEswarRajeshJakki/gemini-youtube-automation) | 373 |
| [DuxSec/videoGenerator](https://github.com/DuxSec/videoGenerator) | 293 |
| [Sfedfcv/redesigned-pancake](https://github.com/Sfedfcv/redesigned-pancake) | 277 |
| [cedroid/groq-bot](https://github.com/cedroid/groq-bot) | 1 |

## Do user-named repos (verified)

| Repo | Stars | Kya hai | Hamare liye kaam ka |
|---|---|---|---|
| [CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) | 6411 | Your always-on AI coworkers that move between text, calls, and Slack. | patterns to borrow: planner/executor split, human-in-the-loop approvals |
| [cedroid/groq-bot](https://github.com/cedroid/groq-bot) | 1 | A RAG-powered WhatsApp auto-reply bot that runs entirely on Android via Termux. No server required. | retrieval + auto-reply pipelines |
