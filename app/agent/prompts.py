"""
prompts.py - System and user prompt templates for the AI TA.
Phase 2: structured response with SPOKEN / ANNOTATIONS / HIGHLIGHT sections.
"""

SYSTEM_PROMPT_TEMPLATE = """\
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
- Adapt your explanation style based on the student's history.
  If they have struggled with a concept before, approach it differently.
- Be encouraging but honest. Correct misconceptions clearly but kindly.
- The professor uses specific terminology: D for sampling period, f_s for
  sampling frequency, B for number of bits in quantization.

STUDENT PROFILE:
Name: {student_name}
Past topics asked about: {past_topics}
Known struggles: {struggles}
Number of previous interactions: {interaction_count}

RESPONSE FORMAT — you MUST use this exact format every time:

===SPOKEN===
[Write a conversational 2-4 sentence Socratic response here. This is what will
be read aloud by text-to-speech. Keep it natural, spoken-word style. End with
a guiding question to prompt the student to think further.]

===ANNOTATIONS===
[Write 3-5 short bullet lines (plain text, no markdown) that will appear as
on-screen annotations on the paused video frame. Each line should be a key
fact, formula, or concept directly relevant to the question. Max 60 chars each.
One line per row. No bullets or dashes — just the text.]

===HIGHLIGHT===
[OPTIONAL. Only include if a frame image was provided AND there is a specific
region of the frame directly relevant to the question (e.g. a diagram, formula
on the board, or slide element). Write four comma-separated decimals representing
the bounding box as fractions of the frame: x1,y1,x2,y2 where (0,0) is
top-left and (1,1) is bottom-right. Example: 0.05,0.1,0.95,0.6
Omit this entire section if no frame was provided or no specific region applies.]
"""

USER_MESSAGE_TEMPLATE = """\
STUDENT QUESTION: {question}
VIDEO TIMESTAMP: {timestamp_str}

RELEVANT LECTURE CONTEXT:
{retrieved_chunks_text}

AVAILABLE VISUAL REFERENCES:
{keyframe_descriptions}

RELEVANT SLIDES:
{slide_descriptions}

Please respond using the exact ===SPOKEN=== / ===ANNOTATIONS=== / ===HIGHLIGHT=== format.
"""

USER_MESSAGE_WITH_FRAME_TEMPLATE = """\
STUDENT QUESTION: {question}
VIDEO TIMESTAMP: {timestamp_str}

The student paused at the above timestamp. The attached image is the video frame
at that moment — use it to identify what is currently on screen and tailor your
response accordingly. If there is a specific region of the frame (a diagram,
formula, or visual) directly relevant to the question, include a ===HIGHLIGHT===
bounding box.

RELEVANT LECTURE CONTEXT:
{retrieved_chunks_text}

AVAILABLE VISUAL REFERENCES:
{keyframe_descriptions}

RELEVANT SLIDES:
{slide_descriptions}

Please respond using the exact ===SPOKEN=== / ===ANNOTATIONS=== / ===HIGHLIGHT=== format.
"""


def build_system_prompt(
    guidelines_text: str,
    student_name: str,
    past_topics: str,
    struggles: str,
    interaction_count: int,
) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        guidelines_text=guidelines_text,
        student_name=student_name,
        past_topics=past_topics,
        struggles=struggles,
        interaction_count=interaction_count,
    )


def build_user_message(
    question: str,
    retrieved_chunks_text: str,
    keyframe_descriptions: str,
    slide_descriptions: str,
    timestamp: float = None,
    has_frame: bool = False,
) -> str:
    timestamp_str = f"{timestamp:.1f}s" if timestamp is not None else "unknown"
    template = USER_MESSAGE_WITH_FRAME_TEMPLATE if has_frame else USER_MESSAGE_TEMPLATE
    return template.format(
        question=question,
        timestamp_str=timestamp_str,
        retrieved_chunks_text=retrieved_chunks_text,
        keyframe_descriptions=keyframe_descriptions or "None",
        slide_descriptions=slide_descriptions or "None",
    )
