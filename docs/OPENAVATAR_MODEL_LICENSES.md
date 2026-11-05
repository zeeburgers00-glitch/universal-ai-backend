# OpenAvatar model license manifest

This file is a conservative integration inventory, not legal advice. Source-code licenses
do not automatically grant rights to model weights, datasets, dependencies, speaker
samples, faces, videos, or generated outputs.

| Component | Code license | Weights/assets | Commercial state in this repository |
|---|---|---|---|
| SadTalker | Apache-2.0 | Checkpoints and dependencies require separate review | Blocked pending review |
| MuseTalk | MIT | Exact weights, deps and dataset terms require review | Blocked pending review |
| OpenVoice V2 | MIT | Weight and dependency review required | Blocked pending review |
| whisper.cpp | MIT | Selected model artifact review required | Blocked pending review |
| FFmpeg | LGPL/GPL depending on build flags | Not applicable | Build configuration review required |
| F5-TTS | MIT code | Published pretrained weights reported as CC-BY-NC | Not approved for commercial use |

The API's model registry exposes the same conservative status. The current JobCreate schema
defaults commercial_use=false. Attempts to submit commercial jobs are rejected until a
future explicit license clearance process is implemented.

Before changing a model to commercially approved:
1. Pin the exact upstream commit, model repository revision, checkpoint files, and hashes.
2. Record SPDX identifiers or exact license texts for code and every weight.
3. Review all transitive dependencies and FFmpeg build flags.
4. Review dataset, identity/voice consent, and output rights.
5. Obtain legal review for ambiguous, non-commercial, or custom terms.
6. Add a test proving that unapproved assets remain blocked.

Official upstream references:
- SadTalker: https://github.com/OpenTalker/SadTalker
- MuseTalk: https://github.com/TMElyralab/MuseTalk
- OpenVoice: https://github.com/myshell-ai/OpenVoice
- Whisper.cpp: https://github.com/ggml-org/whisper.cpp
- FFmpeg: https://ffmpeg.org/legal.html
- F5-TTS: https://github.com/SWivid/F5-TTS
