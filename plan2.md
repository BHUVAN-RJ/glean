# Build 4 SC Hackathon - Phase 2: Chrome Extension + Video Player UI

## Overview

Build two things:
1. A local HTML video player page that hosts the lecture video with a clean, fixed-size UI
2. A Chrome extension that injects an AI TA overlay onto the video player, listens for pause events, captures voice questions, calls the FastAPI backend, and renders animated annotations + voice responses on top of the video

The FastAPI backend from Phase 1 remains unchanged. The extension is a thin client.

---

## System Architecture

```
┌──────────────────────────────────────────────────┐
│              LOCAL VIDEO PLAYER PAGE              │
│                                                   │
│   ┌───────────────────────────────────────────┐   │
│   │                                           │   │
│   │          <video> element                  │   │
│   │          (lecture.mp4)                     │   │
│   │          Fixed: 1280 x 720                │   │
│   │                                           │   │
│   │   ┌───────────────────────────────────┐   │   │
│   │   │  OVERLAY CANVAS (injected by ext) │   │   │
│   │   │  - Animated text annotations      │   │   │
│   │   │  - Highlight boxes (Approach B)   │   │   │
│   │   │  - Dismiss button                 │   │   │
│   │   └───────────────────────────────────┘   │   │
│   │                                           │   │
│   └───────────────────────────────────────────┘   │
│                                                   │
│   [  ▶ Play  ] [   advancement bar  ] [ 🔊 Vol ]  │
│                                                   │
│   Status: 🎤 Listening... / 🤔 Thinking... / TA  │
│                                                   │
└──────────────────────────────────────────────────┘
         │                          │
         │ pause event              │ voice question
         │ + timestamp              │ + frame capture
         ▼                          ▼
┌──────────────────────────────────────────────────┐
│              CHROME EXTENSION                     │
│                                                   │
│   content.js:                                     │
│     - Listens for video pause                     │
│     - Captures current frame via canvas           │
│     - Starts speech recognition                   │
│     - Shows "Listening..." status                 │
│     - Sends question + frame + timestamp to API   │
│     - Receives response                           │
│     - Renders animated text overlay               │
│     - Renders highlight boxes (if any)            │
│     - Plays TTS response                          │
│     - Clears overlay on play/dismiss              │
│                                                   │
│   background.js:                                  │
│     - Manages extension state                     │
│     - Handles API communication                   │
│                                                   │
└──────────────────────────────────────────────────┘
         │
         │ POST /query
         │ { question, student_id, timestamp,
         │   frame_base64 (for Approach B) }
         ▼
┌──────────────────────────────────────────────────┐
│              FASTAPI BACKEND (from Phase 1)       │
│                                                   │
│   - RAG retrieval from ChromaDB                   │
│   - Student profile lookup                        │
│   - Claude API call with all context              │
│   - Returns:                                      │
│     {                                             │
│       answer: str,                                │
│       annotations: [                              │
│         { text, x_pct, y_pct, type: "label" },   │
│         { x_pct, y_pct, w_pct, h_pct,            │
│           label, type: "highlight" }              │
│       ],                                          │
│       lecture_references: [...],                  │
│       referenced_images: [...]                    │
│     }                                             │
└──────────────────────────────────────────────────┘
```

---

## Component 1: Local Video Player Page

A simple, clean HTML page that serves the lecture video.

**File:** `player/index.html`

**Specs:**
- Video element with fixed dimensions: 1280x720
- Source: `lecture.mp4` (served from same directory or from FastAPI static files)
- Standard HTML5 video controls (play, pause, seek, volume)
- Dark background, centered video
- A status bar below the video showing the current AI TA state:
  - Default: "🎓 AI TA Ready - Pause the video to ask a question"
  - On pause: "🎤 Listening for your question..."
  - After speech captured: "🤔 Thinking..."
  - After response: "✅ TA responded - Press play to continue"
- The status bar is updated by the Chrome extension via DOM manipulation
- NO framework needed. Plain HTML + CSS. Keep it minimal and clean.
- Page title: "CSCI 576: Multimedia Systems - Lecture 2"
- Small course info header above the video: "CSCI 576 | Digital Data Acquisition and Media Basics | Prof. Papadopoulos"

**Styling:**
- Background: #1a1a2e (dark navy)
- Video border: subtle 1px solid #333
- Status bar: semi-transparent dark background, white text, rounded corners
- Font: system font stack, clean and readable
- Overall feel: like a modern lecture player (think Coursera/edX but simpler)

---

## Component 2: Chrome Extension

### manifest.json

```json
{
  "manifest_version": 3,
  "name": "AI TA - Lecture Companion",
  "version": "1.0",
  "description": "AI Teaching Assistant that helps you understand lectures",
  "permissions": [
    "activeTab",
    "scripting"
  ],
  "host_permissions": [
    "http://localhost/*",
    "<all_urls>"
  ],
  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "js": ["content.js"],
      "css": ["overlay.css"]
    }
  ],
  "background": {
    "service_worker": "background.js"
  }
}
```

### content.js - Core Logic

**On page load:**
1. Find the `<video>` element on the page
2. If no video element found, do nothing (extension is passive on non-video pages)
3. Create the overlay canvas, position it exactly on top of the video element
4. Create the dismiss button (small X in top-right corner of overlay, hidden by default)
5. Set up the status bar element (or create one if the page doesn't have the expected one)

**On video pause:**
1. Update status: "🎤 Listening for your question..."
2. Capture the current video frame:
   ```javascript
   const canvas = document.createElement('canvas');
   canvas.width = video.videoWidth;
   canvas.height = video.videoHeight;
   canvas.getContext('2d').drawImage(video, 0, 0);
   const frameBase64 = canvas.toDataURL('image/jpeg', 0.8);
   ```
3. Get current timestamp: `video.currentTime`
4. Start speech recognition:
   ```javascript
   const recognition = new webkitSpeechRecognition();
   recognition.continuous = false;
   recognition.interimResults = true;
   recognition.lang = 'en-US';
   recognition.start();
   ```
5. Show interim results in status bar as user speaks
6. On `recognition.onresult` (final result):
   - Update status: "🤔 Thinking..."
   - Send to backend:
     ```javascript
     const response = await fetch('http://localhost:8000/query', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({
         question: transcript,
         student_id: 'demo_student',
         timestamp: video.currentTime,
         frame_base64: frameBase64  // Only for Approach B demos
       })
     });
     ```
7. On response received:
   - Update status: "✅ TA responded - Press play to continue"
   - Render annotations with animation (see Annotation Rendering below)
   - Speak the response via TTS
   - Show dismiss button

**On video play (resume):**
1. Clear all annotations from overlay canvas
2. Stop any ongoing TTS
3. Hide dismiss button
4. Reset status to default

**On dismiss button click:**
1. Clear all annotations from overlay canvas
2. Stop any ongoing TTS
3. Hide dismiss button

**Speech recognition edge cases:**
- If no speech detected for 5 seconds after pause, show status: "🎤 Still listening... ask your question"
- If no speech detected for 10 seconds, stop listening and show: "🎓 No question detected. Press play to continue or pause again to ask."
- If speech recognition errors out (user denied mic permission), fall back to showing a text input box overlay

### Annotation Rendering System

**Text Annotations (Approach A - primary):**

The AI response will contain structured annotation data. Render text annotations on the overlay canvas with a typewriter animation effect.

```javascript
async function renderAnnotations(annotations, overlayCtx, overlayWidth, overlayHeight) {
  // Clear previous annotations
  overlayCtx.clearRect(0, 0, overlayWidth, overlayHeight);

  // Draw semi-transparent background panel for text
  // Position: bottom portion of video, full width
  const panelHeight = Math.min(annotations.length * 40 + 40, overlayHeight * 0.4);
  const panelY = overlayHeight - panelHeight;

  overlayCtx.fillStyle = 'rgba(0, 0, 0, 0.75)';
  roundRect(overlayCtx, 10, panelY, overlayWidth - 20, panelHeight - 10, 10);
  overlayCtx.fill();

  // Render each annotation line with typewriter effect
  let currentY = panelY + 30;
  for (const annotation of annotations) {
    if (annotation.type === 'label') {
      await typewriterText(overlayCtx, annotation.text, 30, currentY, {
        font: '18px "SF Mono", monospace',
        color: annotation.color || '#00FF88',
        speed: 30 // ms per character
      });
      currentY += 35;
    }
  }
}

function typewriterText(ctx, text, x, y, options) {
  return new Promise((resolve) => {
    let i = 0;
    const interval = setInterval(() => {
      // Clear the line area and redraw up to current character
      ctx.font = options.font;
      ctx.fillStyle = options.color;
      ctx.fillText(text.substring(0, i + 1), x, y);
      i++;
      if (i >= text.length) {
        clearInterval(interval);
        resolve();
      }
    }, options.speed);
  });
}
```

**Highlight Annotations (Approach B - for 1-2 demo moments):**

When the response includes a highlight annotation, draw a colored rectangle/circle on the specified region of the video frame.

```javascript
function renderHighlight(ctx, highlight, overlayWidth, overlayHeight) {
  const x = (highlight.x_pct / 100) * overlayWidth;
  const y = (highlight.y_pct / 100) * overlayHeight;
  const w = (highlight.w_pct / 100) * overlayWidth;
  const h = (highlight.h_pct / 100) * overlayHeight;

  // Glowing highlight box
  ctx.strokeStyle = '#FF4444';
  ctx.lineWidth = 3;
  ctx.shadowColor = '#FF4444';
  ctx.shadowBlur = 10;
  ctx.strokeRect(x, y, w, h);
  ctx.shadowBlur = 0;

  // Label
  if (highlight.label) {
    ctx.font = 'bold 14px Arial';
    ctx.fillStyle = '#FF4444';
    ctx.fillText(highlight.label, x, y - 8);
  }
}
```

### overlay.css

```css
#ta-overlay-container {
  position: absolute;
  pointer-events: none;
  z-index: 9999;
}

#ta-dismiss-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  pointer-events: auto;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.4);
  color: white;
  border-radius: 50%;
  width: 30px;
  height: 30px;
  cursor: pointer;
  font-size: 16px;
  display: none;
  z-index: 10000;
}

#ta-dismiss-btn:hover {
  background: rgba(255, 255, 255, 0.4);
}

#ta-status-bar {
  position: absolute;
  bottom: -40px;
  left: 0;
  right: 0;
  text-align: center;
  color: #ccc;
  font-family: system-ui, sans-serif;
  font-size: 14px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.6);
  border-radius: 0 0 8px 8px;
}
```

---

## Component 3: Backend Modifications

### Changes to POST /query endpoint

Add two new optional fields to the request:
- `timestamp`: float (video timestamp in seconds when paused)
- `frame_base64`: string (base64 JPEG of the paused frame, optional, only for Approach B)

When `timestamp` is provided, use it to boost retrieval relevance:
- Query ChromaDB as before with the question text
- But also filter/boost results where the segment's time range contains the given timestamp
- This ensures the retrieved context matches what the student is currently watching

When `frame_base64` is provided (Approach B scenarios):
- Send the frame to Claude Vision API along with the question
- Add to the prompt: "The student paused at this exact frame. If their question relates to something visible, identify ONE region to highlight. Return as: [HIGHLIGHT:x_pct,y_pct,w_pct,h_pct,label] where values are percentages 0-100."

### Changes to response format

Add `annotations` field to the response:

```python
{
    "answer": "Let's think about this step by step...",
    "annotations": [
        {
            "type": "label",
            "text": "📌 Key concept: Sampling period D = distance between samples",
            "color": "#00FF88"
        },
        {
            "type": "label", 
            "text": "→ If D increases: fewer samples, less data, but quality drops",
            "color": "#00BBFF"
        },
        {
            "type": "label",
            "text": "→ If D decreases: more samples, more data, quality improves",
            "color": "#00BBFF"
        },
        {
            "type": "label",
            "text": "🤔 Think: What's the minimum sampling rate to avoid loss?",
            "color": "#FFD700"
        }
    ],
    "highlights": [
        {
            "type": "highlight",
            "x_pct": 45,
            "y_pct": 30,
            "w_pct": 25,
            "h_pct": 15,
            "label": "Sampling period D"
        }
    ],
    "lecture_references": [...],
    "referenced_images": [...]
}
```

### Changes to Claude prompt

Add to the system prompt:

```
RESPONSE FORMAT:
You must return your response in two parts:

1. SPOKEN RESPONSE: A natural, conversational explanation that will be read
   aloud via text-to-speech. Keep it concise (3-5 sentences max). Use
   Socratic questioning.

2. ANNOTATIONS: Key points formatted for on-screen display. These appear
   as text overlaid on the lecture video. Return as a JSON array:
   [
     {"text": "📌 Key point here", "color": "#00FF88"},
     {"text": "→ Sub-point or step", "color": "#00BBFF"},
     {"text": "🤔 Question for the student", "color": "#FFD700"}
   ]
   
   Rules for annotations:
   - Maximum 5 annotation lines
   - Each line maximum 60 characters
   - Use emoji prefixes: 📌 for key concepts, → for steps/details,
     🤔 for Socratic questions, ⚠️ for common mistakes, ✅ for confirmations
   - Color coding: #00FF88 (green) for key concepts, #00BBFF (blue) for
     details, #FFD700 (gold) for questions, #FF4444 (red) for warnings

3. HIGHLIGHT (optional, only when a specific region of the current video
   frame is directly relevant): Return ONE highlight region as:
   [HIGHLIGHT:x_pct,y_pct,w_pct,h_pct,label]
   Only include this if you can see the frame AND a specific visual element
   is relevant to the answer.

Format your response as:
SPOKEN: <your spoken response here>
ANNOTATIONS: <JSON array of annotation objects>
HIGHLIGHT: <optional highlight tag or "none">
```

### Response parsing update

Update `response_parser.py` to parse the new format:

```python
def parse_ta_response(raw_response: str) -> dict:
    """Parse Claude's structured response into spoken text, annotations, and highlights."""
    
    result = {
        "answer": "",
        "annotations": [],
        "highlights": []
    }
    
    # Extract SPOKEN section
    spoken_match = re.search(r'SPOKEN:\s*(.*?)(?=ANNOTATIONS:|$)', raw_response, re.DOTALL)
    if spoken_match:
        result["answer"] = spoken_match.group(1).strip()
    
    # Extract ANNOTATIONS section
    annotations_match = re.search(r'ANNOTATIONS:\s*(\[.*?\])', raw_response, re.DOTALL)
    if annotations_match:
        try:
            annotations = json.loads(annotations_match.group(1))
            result["annotations"] = [
                {"type": "label", "text": a["text"], "color": a.get("color", "#00FF88")}
                for a in annotations
            ]
        except json.JSONDecodeError:
            pass
    
    # Extract HIGHLIGHT
    highlight_match = re.search(
        r'\[HIGHLIGHT:(\d+),(\d+),(\d+),(\d+),(.*?)\]', raw_response
    )
    if highlight_match:
        result["highlights"] = [{
            "type": "highlight",
            "x_pct": int(highlight_match.group(1)),
            "y_pct": int(highlight_match.group(2)),
            "w_pct": int(highlight_match.group(3)),
            "h_pct": int(highlight_match.group(4)),
            "label": highlight_match.group(5).strip()
        }]
    
    return result
```

---

## Project Structure (Phase 2 additions)

```
lecture-ta-pipeline/
├── (all existing Phase 1 files)
├── player/
│   ├── index.html          (local video player page)
│   └── lecture.mp4          (symlink or copy of data/lecture.mp4)
├── extension/
│   ├── manifest.json
│   ├── content.js           (core logic: pause detection, speech,
│   │                         API calls, annotation rendering)
│   ├── overlay.css           (styling for overlay elements)
│   └── background.js        (extension state management)
└── plan2.md                 (this file)
```

---

## Pass/Fail Criteria (Phase 2)

### Video Player Page
- [ ] `player/index.html` loads in Chrome and plays `lecture.mp4`
- [ ] Video element is exactly 1280x720 or scales proportionally
- [ ] Video has standard controls (play, pause, seek, volume)
- [ ] Page has dark theme with course info header
- [ ] Status bar is visible below the video

### Chrome Extension - Core Flow
- [ ] Extension loads without errors (check chrome://extensions)
- [ ] When video is paused, speech recognition starts automatically
- [ ] Status bar updates to "Listening..." on pause
- [ ] Speaking a question captures the transcript correctly
- [ ] Status bar updates to "Thinking..." after speech capture
- [ ] API call to `http://localhost:8000/query` is made with question, timestamp, and student_id
- [ ] Response is received and annotations render on screen
- [ ] TTS speaks the response aloud
- [ ] Status bar updates to "TA responded" after render complete

### Annotation Rendering
- [ ] Text annotations appear with typewriter animation effect
- [ ] Annotations render in a semi-transparent dark panel at the bottom of the video
- [ ] Each annotation line appears one after another (not all at once)
- [ ] Annotation colors match the color coding (green, blue, gold, red)
- [ ] Emoji prefixes are visible and render correctly
- [ ] Maximum 5 annotation lines displayed

### Dismiss and Clear
- [ ] Dismiss button (X) appears in top-right corner when annotations are showing
- [ ] Clicking dismiss clears all annotations and stops TTS
- [ ] Pressing play clears all annotations and stops TTS
- [ ] After clearing, pausing again starts a fresh listening cycle

### Approach B Highlight (for demo only)
- [ ] When the response includes highlight data, a colored rectangle appears on the video at the specified region
- [ ] The highlight has a subtle glow effect
- [ ] A label appears above the highlight box
- [ ] The highlight clears along with text annotations on play/dismiss

### Speech Edge Cases
- [ ] If no speech for 10 seconds, listening stops gracefully with a message
- [ ] If mic permission denied, a text input fallback appears
- [ ] Interim speech results show in the status bar as user speaks

### Demo-Critical Tests
- [ ] Pause at the sampling section (~5 min mark). Ask "What is sampling period?" Voice response explains D and its tradeoffs. Annotations show key formulas.
- [ ] Pause at quantization section (~10 min mark). Ask "What is the maximum error?" Voice response guides through R/(2^B-1)/2. Annotations show step-by-step.
- [ ] For ONE Approach B demo: Pause on a slide showing a diagram. Ask about it. A highlight box appears on the relevant part of the slide.

### Integration
- [ ] FastAPI backend accepts the new `timestamp` and `frame_base64` fields without breaking existing functionality
- [ ] Response includes `annotations` and `highlights` arrays
- [ ] Backend parses Claude's structured response correctly

---

## Timing Estimates (Phase 2)

| Task | Who | Time |
|------|-----|------|
| Build player/index.html | Frontend person | 30 min |
| Build extension manifest + content.js skeleton | Frontend person | 30 min |
| Implement pause detection + speech recognition | Frontend person | 30 min |
| Implement annotation rendering + typewriter animation | Frontend person | 45 min |
| Update FastAPI backend (new fields, prompt changes, response parser) | You (RJ) | 45 min |
| Integration testing | Everyone | 30 min |
| Demo rehearsal | Everyone | 30 min |
| **Total** | | **~3.5 hours** |

**CRITICAL:** The backend changes and extension can be built in parallel. Don't wait for one to finish before starting the other. Agree on the API request/response format (specified above) and build against it independently.

---

## Environment Setup for Extension Development

1. Open `chrome://extensions` in Chrome
2. Enable "Developer mode" (toggle in top right)
3. Click "Load unpacked"
4. Select the `extension/` folder
5. The extension will auto-inject on any page with a `<video>` element
6. Open `player/index.html` in Chrome (serve it via `python -m http.server 8080` in the `player/` directory to avoid CORS issues with the video file)
7. Make sure FastAPI backend is running on `http://localhost:8000`

---

## Demo Day Checklist

Before the demo:
- [ ] FastAPI server running on localhost:8000
- [ ] `python -m http.server 8080` running in `player/` directory
- [ ] Chrome has the extension loaded
- [ ] Two student profiles exist in the database
- [ ] Tested the three demo queries at least twice
- [ ] Mic permissions already granted in Chrome (no popup during demo)
- [ ] Speaker volume tested for TTS playback
- [ ] Backup: if voice fails, have the text input fallback ready