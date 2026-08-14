---
name: prompt-engineering
description: "Refines a rough prompt through interactive one-question-at-a-time honing, then transforms it into an optimized prompt using frameworks (RTF, RISEN, Chain of Thought, RODES, Chain of Density, RACE, RISE, STAR, SOAP, CLEAR, GROW). Use whenever the user wants to improve, refine, optimize, or create a prompt for any AI model — including phrasings like 'make me a prompt', 'how do I ask AI to...', or when they hand over a vague prompt and want it sharpened."
category: automation
risk: safe
source: community
tags: "[prompt-engineering, optimization, frameworks, ai-enhancement]"
date_added: "2026-02-27"
---

## Purpose

This skill transforms raw, unstructured user prompts into highly optimized prompts using established prompting frameworks. It analyzes user intent, identifies task complexity, and intelligently selects the most appropriate framework(s) to maximize Claude/ChatGPT output quality.

Framework selection operates in "magic mode" - it happens silently, and users receive polished, ready-to-use prompts without technical explanations or framework jargon. Requirements gathering, however, is interactive: the skill hones the user's intent through targeted one-at-a-time questions before generating the prompt.

This is a **universal skill** that works in any terminal context, not limited to Obsidian vaults or specific project structures.

## When to Use
Invoke this skill when:

- User provides a vague or generic prompt (e.g., "help me code Python")
- User has a complex idea but struggles to articulate it clearly
- User's prompt lacks structure, context, or specific requirements
- Task requires step-by-step reasoning (debugging, analysis, design)
- User needs a prompt for a specific AI task but doesn't know prompting frameworks
- User wants to improve an existing prompt's effectiveness
- User asks variations of "how do I ask AI to..." or "create a prompt for..."

## Workflow

### Step 1: Analyze Intent

**Objective:** Understand what the user truly wants to accomplish.

**Actions:**
1. Read the raw prompt provided by the user
2. Detect task characteristics:
   - **Type:** coding, writing, analysis, design, learning, planning, decision-making, creative, etc.
   - **Complexity:** simple (one-step), moderate (multi-step), complex (requires reasoning/design)
   - **Clarity:** clear intention vs. ambiguous/vague
   - **Domain:** technical, business, creative, academic, personal, etc.
3. Identify implicit requirements:
   - Does user need examples?
   - Is output format specified?
   - Are there constraints (time, resources, scope)?
   - Is this exploratory or execution-focused?

**Detection Patterns:**
- **Simple tasks:** Short prompts (<50 chars), single verb, no context
- **Complex tasks:** Long prompts (>200 chars), multiple requirements, conditional logic
- **Ambiguous tasks:** Generic verbs ("help", "improve"), missing object/context
- **Structured tasks:** Mentions steps, phases, deliverables, stakeholders


### Step 2: Interactive Questioning (Idea Honing)

**Objective:** Iteratively refine the user's raw prompt into a fully specified intent through targeted Q&A — never assume what the user did not say.

**Constraints:**
- **Ask ONLY ONE question at a time** and wait for the user's response before asking the next.
- Do NOT list multiple questions at once, as this overwhelms the user.
- **Every question is multiple-choice.** Offer 2-4 concrete, mutually exclusive options so the user picks instead of composing an answer. Each option states its consequence for the final prompt (see "carries its own finding" below). The user may always answer outside the options — treat a free-form reply as valid. In Claude Code, present the question via the AskUserQuestion tool when available (it renders options natively and includes "Other" automatically); otherwise render options as a lettered list (A/B/C/D).
- Do NOT pre-populate answers or assume user preferences.
- **A question must carry its own finding.** When a gap or ambiguity forces a choice, the question must be answerable without the user reconstructing your analysis. State the concrete consequence of each option and what actually differs between them — not just the choice.
- **Teach the finding when asked, then re-ask.** If the user replies asking for explanation rather than choosing ("I don't understand this", "explain more"), that is a defect in how you posed the question, not user friction. Explain plainly — what each option changes about the final prompt — then re-ask. Never treat a request for clarification as a decision, and never let an unanswered question fall through into the generated prompt as a silent assumption.
- **Follow the thread.** There is no cap on question count or depth. If an answer raises new questions, surfaces a contradiction, or opens an area that needs clarification, drill into it with follow-up questions before moving to the next topic. Depth is preferred over breadth — fully resolve one thread before starting another.
- Follow this exact sequence for each question:
  1. Formulate a single, targeted question.
  2. Present the question to the user.
  3. Wait for the user's complete response.
  4. If the answer raises follow-ups, ask those next (one at a time) until the thread is resolved; otherwise proceed to the next topic.

**What to probe** (in rough priority order, skipping anything already answered by the raw prompt):
- Task type — coding vs. writing vs. analysis vs. design, if ambiguous
- Target audience/model and how it materially affects the output
- Scope boundaries — what is in and out
- Desired output format and level of detail
- Constraints — time, resources, tone, length, technology
- Edge cases and failure behavior the prompt should handle

**Example Exchange:**

```
User: "help me with AI"

Q1: "What do you want to do with AI?
  A) Build something with it — the prompt will target system design
  B) Learn about it — the prompt will target a study path
  C) Use an AI tool for a task — the prompt will target task instructions"

User: "A"

Q2: "What are you building?
  A) An app that calls an AI model — prompt covers API integration design
  B) An agent/automation — prompt covers agent architecture and tool use
  C) Fine-tuning a model — prompt covers data prep and training strategy"
```

**Completion:** Continue — however many rounds it takes — until all critical uncertainties are resolved and no thread is left dangling, then move straight to Step 3 and deliver the optimized prompt. No summaries, no confirmation round-trips, no transcript files — just questions, then the prompt.


### Step 3: Select Framework(s)

**Objective:** Map task characteristics to optimal prompting framework(s).

**Framework Mapping Logic:**

| Task Type | Recommended Framework(s) | Rationale |
|-----------|-------------------------|-----------|
| **Role-based tasks** (act as expert, consultant) | **RTF** (Role-Task-Format) | Clear role definition + task + output format |
| **Step-by-step reasoning** (debugging, proof, logic) | **Chain of Thought** | Encourages explicit reasoning steps |
| **Structured projects** (multi-phase, deliverables) | **RISEN** (Role, Instructions, Steps, End goal, Narrowing) | Comprehensive structure for complex work |
| **Complex design/analysis** (systems, architecture) | **RODES** (Role, Objective, Details, Examples, Sense check) | Balances detail with validation |
| **Summarization** (compress, synthesize) | **Chain of Density** | Iterative refinement to essential info |
| **Communication** (reports, presentations, storytelling) | **RACE** (Role, Audience, Context, Expectation) | Audience-aware messaging |
| **Investigation/analysis** (research, diagnosis) | **RISE** (Research, Investigate, Synthesize, Evaluate) | Systematic analytical approach |
| **Contextual situations** (problem-solving with background) | **STAR** (Situation, Task, Action, Result) | Context-rich problem framing |
| **Documentation** (medical, technical, records) | **SOAP** (Subjective, Objective, Assessment, Plan) | Structured information capture |
| **Goal-setting** (OKRs, objectives, targets) | **CLEAR** (Collaborative, Limited, Emotional, Appreciable, Refinable) | Goal clarity and actionability |
| **Coaching/development** (mentoring, growth) | **GROW** (Goal, Reality, Options, Will) | Developmental conversation structure |

**Blending Strategy:**
- **Combine 2-3 frameworks** when task spans multiple types
- Example: Complex technical project → **RODES + Chain of Thought** (structure + reasoning)
- Example: Leadership decision → **CLEAR + GROW** (goal clarity + development)

**Selection Criteria:**
- Primary framework = best match to core task type
- Secondary framework(s) = address additional complexity dimensions
- Avoid over-engineering: simple tasks get simple frameworks

**Critical Rule:** This selection happens **silently** - do not explain framework choice to user.

Role: You are a senior software architect. [RTF - Role]

Objective: Design a microservices architecture for [system]. [RODES - Objective]

Approach this step-by-step: [Chain of Thought]
1. Analyze current monolithic constraints
2. Identify service boundaries
3. Design inter-service communication
4. Plan data consistency strategy

Details: [RODES - Details]
- Expected traffic: [X]
- Data volume: [Y]
- Team size: [Z]

Output Format: [RTF - Format]
Provide architecture diagram description, service definitions, and migration roadmap.

Sense Check: [RODES - Sense check]
Validate that services are loosely coupled, independently deployable, and aligned with business domains.
```

**4.5. Language Adaptation**
- If original prompt is in Portuguese, generate prompt in Portuguese
- If original prompt is in English, generate prompt in English
- If mixed, default to English (more universal for AI models)

**4.6. Quality Checks**
Before finalizing, verify:
- [ ] Prompt is self-contained (no external context needed)
- [ ] Task is specific and measurable
- [ ] Output format is clear
- [ ] No ambiguous language
- [ ] Appropriate level of detail for task complexity


## Critical Rules

### **NEVER:**

- ❌ Assume information that wasn't provided - ALWAYS ask if critical details are missing
- ❌ Explain which framework was selected or why (magic mode - keep it invisible)
- ❌ Generate generic, one-size-fits-all prompts - always customize to context
- ❌ Use technical jargon in the final prompt (unless user's domain is technical)
- ❌ Ask more than ONE question at a time (one question, wait for answer, then the next)
- ❌ Include meta-commentary in the output ("This prompt uses...", "Note that...")
- ❌ Present output without code block formatting
- ❌ Mix languages inconsistently (if user writes in PT, respond in PT)

### **ALWAYS:**

- ✅ Analyze intent before generating (Step 1 is mandatory)
- ✅ Hone intent through one-at-a-time multiple-choice questions until critical uncertainties are resolved (Step 2)
- ✅ Select framework(s) based on task type and complexity (Step 3 mapping)
- ✅ Blend multiple frameworks when it improves prompt quality
- ✅ Adapt prompt length to original input complexity (simple → short, complex → detailed)
- ✅ Include output format specification in generated prompts
- ✅ Present final prompt in clean Markdown code block
- ✅ Make prompts self-contained (no dependency on external context)
- ✅ Use examples in complex prompts to illustrate expected output
- ✅ Validate prompt completeness before presenting (quality checks in Step 4.6)


### **Example 2: Complex Clear Prompt → RODES + Chain of Thought (No Clarification)**

**User Input:**
```
copilot> create prompt for: I need to build a product recommendation system considering purchase history, user preferences, and market trends
```

**Skill Internal Process:**
1. **Analyze:** Clear intent, complex task (ML system design), technical domain
2. **Clarify:** Skip (sufficient information)
3. **Select:** RODES (complex design) + Chain of Thought (reasoning needed)

**Skill Output:**

````markdown
```
Role: You are a senior machine learning engineer specializing in recommendation systems.

Objective: Design a product recommendation system that combines user purchase history, preferences, and market trends.

Details:
- Input data sources: user transaction logs, preference surveys, market trend APIs
- Algorithm considerations: collaborative filtering, content-based filtering, hybrid approaches
- Performance metrics: precision, recall, diversity, novelty
- Scalability: system must handle 100k+ users
- Real-time constraints: recommendations updated within 500ms

Approach step-by-step:
1. Analyze the three data sources and their relationships
2. Propose 2-3 algorithm approaches with trade-offs analysis
3. Design data pipeline architecture (ingestion, processing, serving)
4. Define evaluation metrics and A/B testing strategy
5. Outline implementation roadmap with phases

Examples:
- Show pseudocode for core recommendation logic
- Illustrate data flow diagram
- Provide sample API response structure

Sense Check: Validate that the proposed solution balances personalization with discovery, scales to production load, and incorporates real-time market trends effectively.

Output format: Technical design document with architecture diagrams, algorithm justification, and implementation roadmap.
```
````


### **Example 4: Code Debugging → Chain of Thought**

**User Input:**
```
copilot> optimize prompt: my Python code isn't working, needs debugging
```

**Skill Internal Process:**
1. **Analyze:** Debugging task, needs step-by-step reasoning
2. **Clarify:** Skip (user will provide code context later)
3. **Select:** Chain of Thought

**Skill Output:**

````markdown
```
You are an expert Python debugger.

Task: Debug the Python code provided by the user by analyzing it step-by-step.

Debugging approach:
1. Read and understand the code's intended purpose
2. Identify the error or unexpected behavior
3. Trace variable states at each execution step
4. Locate the root cause of the issue
5. Propose fix with explanation
6. Suggest preventive measures to avoid similar bugs

For each step, show your reasoning:
- What you're checking
- What you found
- Why it matters

Output format:
- **Issue identified:** [Describe the bug]
- **Root cause:** [Why it's happening]
- **Fix:** [Corrected code with comments]
- **Prevention:** [Best practices to avoid this in the future]

Include a working example to verify the fix.
```
````


## Notes

This skill is **platform-agnostic** and works in any terminal context where GitHub Copilot CLI is available. It does not depend on:
- Obsidian vault structure
- Specific project configurations
- External files or templates

The skill is entirely self-contained, operating purely on user input and framework knowledge.

## Limitations
- Use this skill only when the task clearly matches the scope described above.
- Do not treat the output as a substitute for environment-specific validation, testing, or expert review.
- Stop and ask for clarification if required inputs, permissions, safety boundaries, or success criteria are missing.
