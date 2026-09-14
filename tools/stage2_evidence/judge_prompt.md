# guest_present Stage-2 multimodal judge v0.1

You receive one evidence packet for a YouTube video. Use ONLY the supplied metadata, caption text, and sampled visual frames.

Feature definition:
`guest_present = 1` when a non-Chim person is an active content participant.
Exclude staff, delivery/background people, and people who appear only inside external media.

Rules:
1. Judge the specific video unit. A Short does not inherit a guest from its source long-form video.
2. Do not use views, likes, comments, audience response, or performance.
3. `1` only when evidence clearly shows a non-host active participant.
4. `0` only when supplied evidence provides enough coverage to reasonably exclude a guest.
5. Otherwise return `U`. Never force 0/1.
6. Visual evidence may establish presence; captions may support whether that person is participating rather than merely background.
7. Return strict JSON.

Output:
{
  "video_id": "...",
  "feature": "guest_present",
  "label": "0|1|U",
  "confidence": "low|medium|high",
  "evidence": [
    {"type":"visual|caption|metadata","detail":"...","timestamp_sec":12.3}
  ]
}
