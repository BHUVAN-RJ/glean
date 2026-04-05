# Build 4 SC Hackathon - AI TA Video Pipeline Architecture

## Project Overview

Build a FastAPI service that processes a CSCI 576 (Multimedia Systems) lecture video and transcript into a searchable knowledge base, then exposes endpoints for an AI TA agent to retrieve relevant lecture context (text + keyframe images) and generate personalized, Socratic responses via the Claude API.

---

## Input Files

The following files will be in a `data/` folder at the project root:

- `lecture.mp4` - ~2 hour lecture video (single stream that switches between slides, professor face, and hand-drawn diagrams on second camera)
- `transcript.txt` - Plain text transcript from Panopto (NO timestamps, ~2600 lines, auto-generated with minor inaccuracies)
- `slides.pdf` - Professor's lecture slides (will be added)
- `guidelines.txt` - Course syllabus/guidelines defining how the TA should behave (will be added)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  DATA PROCESSING (run once)          │
│                                                      │
│  transcript.txt ──> Whisper Alignment ──> Timestamped│
│                     (audio from mp4)     Transcript  │
│                                                      │
│  Timestamped    ──> Claude Topic     ──> Semantic    │
│  Transcript         Segmentation         Chunks      │
│                                                      │
│  lecture.mp4    ──> Keyframe         ──> PNG frames   │
│                     Extraction           per chunk    │
│                                                      │
│  slides.pdf     ──> Page Extraction  ──> Slide images │
│                                                      │
│  All of above   ──> ChromaDB         ──> Vector Store │
│                     Embedding/Storage                │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                  FASTAPI SERVICE (runtime)           │
│                                                      │
│  POST /query                                         │
│    Input: { question, student_id }                   │
│    Process:                                          │
│      1. Retrieve top-k chunks from ChromaDB          │
│      2. Load student profile (past topics, struggles)│
│      3. Load course guidelines                       │
│      4. Gather associated keyframe images            │
│      5. Call Claude API with all context              │
│      6. Update student profile with new topic        │
│      7. Return response + image references           │
│    Output: {                                         │
│      answer: str,                                    │
│      referenced_images: [{ path, timestamp, desc }], │
│      lecture_references: [{ topic, start_time }]     │
│    }                                                 │
│                                                      │
│  POST /process-lecture                               │
│    Triggers the data processing pipeline             │
│                                                      │
│  GET /student/{student_id}/profile                   │
│    Returns the student's knowledge profile           │
│                                                      │
│  GET /health                                         │
│    Health check                                      │
│                                                      │
│  Static file serving for keyframe images             │
│    GET /frames/{filename}                            │
└─────────────────────────────────────────────────────┘
```

---

## Detailed Component Specifications

### Component 1: Timestamp Alignment

**Problem:** The Panopto transcript is plain text with no timestamps. We need timestamps to link transcript segments to video frames.

**Approach:** Use OpenAI Whisper to transcribe the audio and generate word-level timestamps. Then use the Whisper output as the primary timestamped transcript (it will be comparable or better quality than Panopto's auto-generated one).

**Implementation:**
- Extract audio from `lecture.mp4` using ffmpeg: `ffmpeg -i lecture.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 audio.wav`
- Run Whisper with `--model medium` and `--word_timestamps True` to get timestamped segments
- Output: JSON file with segments, each having `start`, `end`, and `text` fields
- If Whisper takes too long (>20 min), fall back to `--model base` which is faster but less accurate
- Store as `data/timestamped_transcript.json`

**IMPORTANT:** If Whisper is taking too long or fails, use this fallback: estimate timestamps proportionally. The transcript has ~2600 lines, the video is ~2 hours (7200 seconds). Each line gets an estimated timestamp of `(line_number / total_lines) * total_duration`. This is approximate but sufficient for a demo.

### Component 2: Topic Segmentation

**Problem:** We need semantically meaningful chunks, not arbitrary time-window splits.

**Approach:** Send the timestamped transcript to Claude API in batches (~20 min windows) and ask it to identify topic boundaries.

**Implementation:**
- Split timestamped transcript into overlapping windows (20 min each, 2 min overlap)
- For each window, call Claude API with this prompt:

```
You are analyzing a Multimedia Systems (CSCI 576) lecture transcript.
Identify distinct topic segments in this transcript excerpt.
For each segment, provide:
1. A short descriptive title (e.g., "Sampling Period and Frequency Tradeoffs")
2. A 2-3 sentence summary of what is taught
3. The start and end timestamps
4. Key terms and concepts mentioned
5. Whether the professor draws a diagram or references a visual (look for phrases like "as you can see", "look at this", "let me draw", "on this slide", "on the screen")

Return as JSON array:
[{
  "title": "...",
  "summary": "...",
  "start_time": float,
  "end_time": float,
  "key_concepts": ["..."],
  "has_visual_reference": bool,
  "visual_cue_timestamps": [float]
}]
```

- Merge results across windows, resolving overlaps
- Expected output: 15-30 topic segments for a 2-hour lecture
- Store as `data/topic_segments.json`

### Component 3: Keyframe Extraction

**Problem:** We need representative images from the video for visual context, especially when the professor draws diagrams or shows slides.

**Approach:** Extract frames at two types of moments:
1. At the start of each topic segment (for a representative frame)
2. At visual cue timestamps identified in Component 2 (when professor references something visual)

**Implementation:**
- Use ffmpeg to extract frames at specific timestamps:
  ```
  ffmpeg -ss {timestamp} -i lecture.mp4 -frames:v 1 -q:v 2 frames/frame_{segment_id}_{timestamp}.jpg
  ```
- For each topic segment, extract:
  - 1 frame at segment start
  - 1 frame at segment midpoint
  - Frames at each `visual_cue_timestamp`
- Store all frames in `data/frames/` directory
- Create a manifest file `data/frame_manifest.json` mapping each frame to its segment, timestamp, and description

**Frame Descriptions (optional but valuable for retrieval):**
- For the most important frames (those with `has_visual_reference=True`), send to Claude Vision API with prompt: "Briefly describe what is shown in this lecture frame. Is it a slide, a hand-drawn diagram, the professor speaking, or something else? If it's a diagram or slide, describe the key content."
- Store descriptions in the manifest. These descriptions become searchable text in ChromaDB.

### Component 4: Slide Processing

**Problem:** The professor's slides contain structured information that should be separately searchable.

**Approach:** Convert each slide page to an image, extract text, and store alongside the lecture chunks.

**Implementation:**
- Use `pdf2image` to convert each slide page to a PNG
- Use Claude Vision API to extract text and describe the content of each slide
- Store in `data/slides/` directory
- During ChromaDB ingestion, link slides to their corresponding topic segments (match by key concepts or temporal proximity)

### Component 5: ChromaDB Vector Store

**Problem:** Need fast semantic search across all lecture content.

**Approach:** Store topic segments as documents in ChromaDB with rich metadata.

**Implementation:**
- Use `chromadb` with `sentence-transformers` embedding function (`all-MiniLM-L6-v2`)
- Each document in the collection contains:
  - `document`: The full transcript text for that topic segment
  - `metadata`:
    - `topic_title`: str
    - `summary`: str
    - `start_time`: float (seconds)
    - `end_time`: float (seconds)
    - `key_concepts`: str (comma-separated)
    - `lecture_num`: int
    - `keyframe_paths`: str (comma-separated file paths)
    - `slide_paths`: str (comma-separated, if matched)
    - `has_diagram`: bool
  - `id`: unique segment ID

- Create a persistent ChromaDB at `data/chroma_db/`

### Component 6: Student Profile Store

**Problem:** Need lightweight per-student memory across sessions.

**Approach:** SQLite database with simple schema.

**Implementation:**
- Database at `data/students.db`
- Table: `students`
  - `student_id` TEXT PRIMARY KEY
  - `name` TEXT
  - `created_at` TIMESTAMP
- Table: `interactions`
  - `id` INTEGER PRIMARY KEY
  - `student_id` TEXT (FK)
  - `question` TEXT
  - `topic` TEXT (which topic segment was most relevant)
  - `key_concepts` TEXT (concepts discussed)
  - `timestamp` TIMESTAMP
- Table: `struggles`
  - `id` INTEGER PRIMARY KEY
  - `student_id` TEXT (FK)
  - `concept` TEXT
  - `details` TEXT
  - `resolved` BOOLEAN DEFAULT FALSE
  - `timestamp` TIMESTAMP

- Helper functions:
  - `get_student_profile(student_id)` -> returns name, past topics, struggles
  - `update_student_profile(student_id, question, topic, concepts)` -> logs interaction
  - `add_struggle(student_id, concept, details)` -> logs a misconception

### Component 7: Claude API Integration

**Problem:** Need to construct effective prompts that combine course context, retrieved chunks, student history, and pedagogical guidelines.

**Approach:** Build a prompt construction function that assembles all context and calls Claude API.

**Implementation:**

System prompt template:
```
You are an AI Teaching Assistant for CSCI 576: Multimedia Systems at USC,
taught by Professor Papadopoulos.

COURSE GUIDELINES:
{guidelines_text}

YOUR BEHAVIOR:
- Use Socratic questioning: guide students to answers, don't just give them.
- When a student asks about a homework problem, NEVER give the direct solution.
  Instead, ask them what they've tried, identify where their understanding breaks
  down, and guide them step by step.
- Stay within the scope of what has been taught in the lectures so far.
  Do not introduce concepts, libraries, or techniques not covered in class.
- When referencing visual content (diagrams, slides), use the tag
  [SHOW_IMAGE:filename] to tell the frontend which image to display.
- When referencing a specific lecture moment, use the tag
  [LECTURE_REF:start_time] so the frontend can link to that timestamp.
- Adapt your explanation style based on the student's history.
  If they have struggled with a concept before, approach it differently
  this time.
- Be encouraging but honest. If a student's understanding is wrong,
  clearly but kindly correct it.
- The professor uses specific terminology and notation. Match it.
  For example, he uses "D" for sampling period, "f_s" for sampling frequency,
  "B" for number of bits in quantization.

STUDENT PROFILE:
Name: {student_name}
Past topics asked about: {past_topics}
Known struggles: {struggles}
Number of previous interactions: {interaction_count}
```

User message template:
```
STUDENT QUESTION: {question}

RELEVANT LECTURE CONTEXT:
{retrieved_chunks_text}

AVAILABLE VISUAL REFERENCES:
{keyframe_descriptions_with_filenames}

RELEVANT SLIDES:
{matched_slide_descriptions_with_filenames}

Please answer the student's question using the lecture context provided.
Reference specific images and lecture moments where helpful.
```

**Response Parsing:**
- Extract `[SHOW_IMAGE:filename]` tags from response
- Extract `[LECTURE_REF:timestamp]` tags from response
- Return structured response with text, image references, and lecture timestamps

---

## FastAPI Endpoints

### POST /process-lecture
Triggers the full data processing pipeline (Components 1-5).
- Request: `{}` (no body needed, processes files in `data/` folder)
- Response: `{ "status": "success", "segments_created": int, "frames_extracted": int }`
- This is run once before the demo.

### POST /query
Main endpoint for the AI TA.
- Request:
  ```json
  {
    "question": "What happens if D increases in sampling?",
    "student_id": "student_001"
  }
  ```
- Response:
  ```json
  {
    "answer": "Good question! Let me ask you something first...",
    "referenced_images": [
      {
        "path": "/frames/frame_seg3_312.jpg",
        "timestamp": 312.5,
        "description": "Diagram showing sampling period D and frequency tradeoff"
      }
    ],
    "lecture_references": [
      {
        "topic": "Sampling Period and Frequency Tradeoffs",
        "start_time": 290.0,
        "end_time": 380.0
      }
    ],
    "student_profile_updated": true
  }
  ```

### GET /student/{student_id}/profile
Returns student's interaction history.
- Response:
  ```json
  {
    "student_id": "student_001",
    "name": "RJ",
    "past_topics": ["Sampling", "Quantization"],
    "struggles": [{"concept": "aliasing", "details": "confused spatial and temporal aliasing"}],
    "total_interactions": 5
  }
  ```

### POST /student/{student_id}
Create or update a student profile.
- Request: `{ "name": "RJ" }`

### GET /frames/{filename}
Static file serving for keyframe images.

### GET /slides/{filename}
Static file serving for slide images.

### GET /health
Returns `{ "status": "ok" }`

---

## Project Structure

```
lecture-ta-pipeline/
├── data/
│   ├── lecture.mp4
│   ├── transcript.txt
│   ├── slides.pdf
│   ├── guidelines.txt
│   ├── timestamped_transcript.json    (generated)
│   ├── topic_segments.json            (generated)
│   ├── frame_manifest.json            (generated)
│   ├── frames/                        (generated)
│   ├── slides_images/                 (generated)
│   ├── chroma_db/                     (generated)
│   └── students.db                    (generated)
├── app/
│   ├── __init__.py
│   ├── main.py                        (FastAPI app, endpoints)
│   ├── config.py                      (API keys, paths, constants)
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── transcription.py           (Whisper alignment or fallback)
│   │   ├── segmentation.py            (Claude-based topic segmentation)
│   │   ├── keyframes.py               (ffmpeg frame extraction)
│   │   ├── slides.py                  (PDF to images + descriptions)
│   │   └── pipeline.py                (orchestrates all processing steps)
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── vectorstore.py             (ChromaDB setup, query, ingestion)
│   │   └── context_builder.py         (assembles full context for Claude)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── claude_client.py           (Claude API calls)
│   │   ├── prompts.py                 (system + user prompt templates)
│   │   └── response_parser.py         (extracts image/lecture refs)
│   └── student/
│       ├── __init__.py
│       └── profile.py                 (SQLite student profile CRUD)
├── requirements.txt
├── .env                               (ANTHROPIC_API_KEY)
├── plan.md                            (this file)
└── README.md
```

---

## Dependencies (requirements.txt)

```
fastapi==0.115.0
uvicorn==0.30.0
openai-whisper==20240930
chromadb==0.5.0
sentence-transformers==3.0.0
anthropic==0.40.0
pdf2image==1.17.0
Pillow==10.4.0
python-dotenv==1.0.1
python-multipart==0.0.9
pydantic==2.9.0
```

System dependency: `ffmpeg` must be installed (`brew install ffmpeg` on Mac).
System dependency: `poppler` must be installed for pdf2image (`brew install poppler` on Mac).

---

## Pass/Fail Criteria

The pipeline is DONE when ALL of the following pass:

### Processing Pipeline
- [ ] `POST /process-lecture` completes without error
- [ ] `data/timestamped_transcript.json` exists and contains segments with start/end times
- [ ] `data/topic_segments.json` exists and contains 10+ topic segments with titles, summaries, timestamps, and key concepts
- [ ] `data/frames/` contains at least 30 extracted keyframe images
- [ ] `data/chroma_db/` exists and contains indexed documents
- [ ] Total processing time < 30 minutes

### Query Endpoint
- [ ] `POST /query` with a simple question returns a response within 10 seconds
- [ ] Response contains `answer` field with actual Socratic-style text (not empty)
- [ ] Response contains `referenced_images` array (may be empty for some questions)
- [ ] Response contains `lecture_references` array with at least one entry
- [ ] Asking "What is sampling?" returns context related to the sampling portion of the lecture, NOT quantization or TV history
- [ ] Asking the same question for two different student_ids works correctly

### Student Profile
- [ ] `POST /student/student_001` with `{"name": "RJ"}` creates a profile
- [ ] `GET /student/student_001/profile` returns the profile
- [ ] After a `/query` call, the student's `past_topics` list updates
- [ ] Asking a second question shows the previous topic in the student profile context

### Image Serving
- [ ] `GET /frames/{any_existing_frame}` returns a valid image
- [ ] Keyframe filenames in query responses are accessible via the frames endpoint

### Demo-Critical Tests
- [ ] Query: "When the professor talked about quantization error, what did he mean by maximum error being half the interval?" -> Response references the R/(2^B - 1)/2 formula and retrieves the relevant lecture segment
- [ ] Query: "What is the assignment about?" -> Response accurately describes the resampling/quantization programming assignment from the end of the lecture
- [ ] Two different students asking the same question get the same factual content but potentially different framing based on their profiles

---

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=your_key_here
WHISPER_MODEL=medium
CHROMA_PERSIST_DIR=data/chroma_db
DATA_DIR=data
```

---

## Timing Estimates

| Step | Time |
|------|------|
| Whisper transcription (medium model, 2hr video) | 15-25 min |
| Topic segmentation (6 Claude API calls) | 5-8 min |
| Keyframe extraction (ffmpeg, ~50 frames) | 2-3 min |
| Slide processing (PDF + Claude Vision) | 3-5 min |
| ChromaDB ingestion | 1-2 min |
| **Total processing** | **~30-40 min** |

**CRITICAL:** Start the processing pipeline IMMEDIATELY when the hackathon begins. It runs mostly unattended. While it processes, work on the FastAPI endpoints and Claude integration.

---

## Fallback Plan

If Whisper takes too long (>25 min):
1. Kill Whisper
2. Use the proportional timestamp estimation fallback: each line in `transcript.txt` maps to `(line_num / 2602) * video_duration_seconds`
3. This is approximate but sufficient for the demo

If Claude API rate limits hit during segmentation:
1. Manually split the transcript into ~15 chunks of roughly equal size
2. Assign topic titles manually based on reading the transcript
3. This takes 15 min of manual work but avoids API dependency during processing

If pdf2image/poppler fails:
1. Skip slide processing entirely
2. The transcript + keyframes are enough for a strong demo
3. Mention slide integration as a "next step" to judges