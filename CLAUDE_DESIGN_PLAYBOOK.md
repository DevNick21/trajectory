# CLAUDE_DESIGN_PLAYBOOK.md — Visual Production Guide

> How to use Claude Design + Screen.studio to produce the demo video.
> Aesthetic: clean, confident, "this is a real product", not "hackathon toy".

---

## 1. Video structure recap

**Total length: ~3:00** (hard cap: 3:00)

| Time | Segment | Tool |
|------|---------|------|
| 0:00–0:15 | Opening title card + voiceover hook | Claude Design still → video edit |
| 0:15–2:20 | Animated text-based narrative (friend recommends job → user moves to Trajectory) | Screen.studio + Claude Design chat mockups |
| 2:20–3:00 | Real footage: live Telegram bot running on laptop | Screen.studio raw recording, lightly styled |

---

## 2. Aesthetic brief — stick to this

Keep the whole video visually consistent. Pick once, apply everywhere:

| Element | Choice |
|---------|--------|
| Primary colour | One — e.g. deep teal `#0F4C5C` or warm charcoal `#1F2937` |
| Accent | One — e.g. muted coral `#F29E4C` or a soft amber |
| Type face | One — Inter or SF Pro. No decorative fonts. |
| Chat app aesthetic | Clean iMessage-style or Telegram-style. Do not mix. |
| Background | Muted off-white `#FAFAF6` or soft dark `#0B0E11` — pick light or dark and stay |
| Motion | Subtle. Messages slide in bottom-up. No bounces, no spinners unless meaningful. |
| Sound | Optional. If used: minimal ambient music under 15% volume. No stock music clichés. |

The worst visual tell of hackathon work is too many fonts, too many colours, and motion for the sake of it. Pick few choices, apply ruthlessly.

---

## 3. Claude Design prompt templates

Claude Design lives at `claude.ai/design`. It's best at static design, weaker at precise timing animation. Use it for the still frames that you then stitch into the video. Each prompt below is intentionally specific — Claude Design rewards detail.

### 3.1 Opening title card (0:00–0:03)

```
Design a full-screen opening title card for a short product video.

Dimensions: 1920x1080.

Content:
- Product name: "Trajectory"
- Tagline underneath: "A UK job search PA that tells you the truth"
- No author name, no logo, no additional text

Aesthetic: Clean, confident, restrained. Off-white background
(#FAFAF6). Primary colour deep teal (#0F4C5C) for the product name.
Tagline in a muted grey (#6B7280), smaller, one line.

Typography: Inter. Product name ~180pt, tagline ~32pt. Generous
whitespace. Text slightly left-of-centre, not dead centre.

Feel: The opening frame of a Stripe or Linear product video — not
a hackathon slide. No illustrations. No decorative elements. Type
carries everything.
```

### 3.2 Friend's message card / chat bubble (0:15–0:30)

This is the "friend recommends a job" moment. Produce a mockup of an iMessage or WhatsApp conversation where a friend says something like "saw this job, thought of you" with a link.

```
Design a still frame showing an iMessage conversation on a phone
screen, in dark mode.

Dimensions: 1080x1920 (phone portrait).

Content: 3 messages visible, bottom-aligned.
- Message 1 (friend, received): "Saw this. Thought of you — sponsor
  says yes on paper, vibes feel off"
- Message 2 (friend, received, with URL): "https://[redacted]/jobs/
  ml-engineer-uk" — URL shown as a clean link preview card showing
  the job title "ML Engineer" and company placeholder "company.com"
- Message 3 (you, sent): "Let me check. Sending to my PA."

Aesthetic: iOS iMessage dark mode. Friend's bubbles in the iOS grey
(#2C2C2E). Your bubbles in iOS blue (#0A84FF). System font.

Phone frame: subtle, modern. Show the top bar with time (11:47) and
a realistic battery/signal cluster. No carrier name. No notch —
recent flat top.

Feel: Caught in the middle of a real conversation. Not staged. No
emojis.
```

Produce 3–4 variants of this — you'll need slightly different states for the animation (just the first message, then two, then all three). Claude Design can give you each variant with small prompts.

### 3.3 Transition card (0:30–0:33)

Brief visual moment when the user "moves to Trajectory". Could be:

```
Design a 1920x1080 still showing a message-app transition metaphor.

Left side: the iMessage conversation from the previous frame, but
small and in the corner, subtle.

Centre-right: a Telegram-style chat that's empty except for the
pasted URL and a typing indicator.

The visual suggests the job URL moving from one app to another —
but subtly, not with a big arrow.

Colour scheme: same as established. Off-white background, deep
teal accents.

Typography: Inter. No heavy text.

Feel: A quiet cut, not a fanfare. The product just works.
```

### 3.4 Trajectory chat mockups (0:33–2:00)

The bulk of the animated section. Multiple frames showing the Trajectory bot's replies as the user forwards the job and then asks for salary advice.

```
Design a Telegram-style chat interface showing a conversation with
a bot named "Trajectory".

Dimensions: 1080x1920 (phone portrait).

Content: show the following exchange, bottom-aligned, most recent
message visible:

Bot: "Looking into this one..."
Bot (slightly later, bubble appearing below): "Running 8 checks in
parallel" + a small animated-looking status list:
  ✓ Company scraped
  ✓ Sponsor register
  ✓ Companies House
  ✓ Glassdoor
  ✓ Ghost job score
  ✓ Salary data
  ✓ SOC threshold
  ✓ Red flags

Bot (verdict card):
  "⚠ Don't apply"
  Sub-text (smaller, dimmer): "3 hard blockers"
  A tappable button or subtle row saying "See why →"

Aesthetic: Telegram's light mode. Bot profile picture is a simple
geometric mark — a single deep-teal circle with a lowercase "t"
inside, clean type.

Typography: SF Pro or Inter. Bot messages in sans-serif, small
technical details in monospace (the status list).

The 8 checkmarks should look like they were written progressively —
not all the same grey.

Feel: A product that respects the user's time. No loading
animations. Just clean sequential reveals.
```

Produce multiple variants — you need at least:
1. First bot reply only
2. Status list appearing progressively
3. Verdict card added at the bottom
4. A separate frame with the verdict expanded showing the 3 hard blockers with citations

### 3.5 Verdict detail view (expanded)

```
Design a Telegram-style bot response showing an expanded verdict
explanation with 3 hard blockers and citations.

Dimensions: 1080x1920.

Content:
Bot message card, expanded view:

HEADLINE (bold, slightly larger):
"Don't apply — this company isn't on the UK Sponsor Register."

Underneath, in a stacked list:

1. ⛔ NOT ON SPONSOR REGISTER
   "No record found in the register of licensed sponsors
   (updated 20 April 2026)"
   [cite] gov.uk/sponsor-register

2. ⛔ LIKELY GHOST JOB
   "Posting reposted 3 times in the last 12 weeks. Not on the
   company's own careers page."
   [cite] posting metadata + company careers scan

3. ⛔ SALARY BELOW MARKET FLOOR
   "Offered £42k. Market 10th percentile for ML Engineer in
   London: £58k."
   [cite] Levels.fyi + Glassdoor

Each "[cite]" is a small pill, subtle, in the accent colour.

Aesthetic: same Telegram light mode. Citations feel clickable but
aren't loud. The ⛔ icons are small, consistent, not attention-
stealing.

Typography: same as previous frames. Headline slightly heavier
weight.

Feel: Like a receipt. Evidence-first.
```

### 3.6 Salary advice frame (1:30–2:00)

```
Design a Telegram-style bot response showing personalised salary
advice.

Dimensions: 1080x1920.

Content:
User (sent): "salary for that UK ML role I forwarded earlier"

Bot response card:

HEADLINE:
"Opening: £68,000"

Below headline:
Floor: £58,000 (8.6k above your SOC threshold)
Ceiling: £78,000 (90th pct for the role at this company size)

Section below, labelled "When the recruiter asks:"
Script in quotes: "Based on the scope of the role and comparable
positions, I'd be looking for around £68,000. Happy to walk
through the package once I understand what you've budgeted."

Confidence pill (small): MEDIUM (3 sources, 12% spread)

Aesthetic: same established design. Numbers are the hero. The
script is in italics, slightly indented.

Typography: SF Pro. The £68,000 is larger than the rest.

Feel: This is the moment. Keep it clean. Numbers do the work.
```

### 3.7 Closing card (3:00)

```
Design a 1920x1080 closing frame for the video.

Content:
- Top: small product mark (lowercase "t" in deep-teal circle, same
  as the bot avatar)
- Middle-centre: text block
  Line 1: "Built during Built with Opus 4.7 —"
  Line 2 (larger, bolder): "Trajectory"
  Line 3 (smaller, dim): "Open source. Never auto-applies."
- Bottom-left: URL placeholder "github.com/[user]/trajectory"
- Bottom-right: the kene name or handle

Aesthetic: matches the opening card. Off-white background. Deep
teal mark. Muted grey secondary text.

Typography: Inter. Minimal.

Feel: Confident signoff. Not a wall of credits.
```

---

## 4. Screen.studio workflow

Screen.studio produces cinematic screen recordings with automatic cursor smoothing, zoom-on-click, and backgrounds.

### 4.1 For the animated text section (0:15–2:20)

The cleanest path is:

1. Produce the Claude Design still frames above.
2. Stitch them in a simple timeline tool (Premiere / Final Cut / CapCut / DaVinci). Just cross-fade between them with 150–250ms fades.
3. Add a subtle motion layer — for each new chat bubble, have it appear with a 200ms slide-up-and-fade-in. Most video editors have this as a preset.
4. Voiceover across the top, pacing slower than feels natural — breathing room beats density.

Claude Design can generate *images*, not animations. Rive or After Effects do animation. Since neither is in scope this week, frames + cross-fades in a timeline editor is the right choice. Don't chase "real" animation.

### 4.2 For the real footage segment (2:20–3:00)

This is the most important 40 seconds of the video. Judges need to believe the code is real.

Setup before recording:
- Phone running Telegram (or desktop Telegram, whichever shows cleaner).
- Laptop running `uv run python -m trajectory.bot.app`.
- Pre-selected demo job URL that you've tested ≥3 times end-to-end and you know will work.
- Bot conversation already has the onboarded user profile — don't re-onboard on camera.

Recording shots (either on phone screen recording, or Screen.studio on desktop if using Telegram desktop):

1. **0:00–0:15** (of the 40s segment): forward the pre-tested URL to the bot. Watch the status list populate in real time. Verdict arrives.
2. **0:15–0:30**: type "salary for this role" — the salary advice arrives with the real numbers from the real pipeline.
3. **0:30–0:40**: brief cut to the Streamlit dashboard showing the session history, one previous session visible, click in, show the ResearchBundle JSON pretty-printed.

**Why this sequence:** the judge sees live text entry, live parallel agents working, real numbers, real citations clickable, and a real database persisting sessions. That's "this is a working product" — not "this is a demo-day fake".

### 4.3 Rules for the live segment

- Do not narrate over the live segment. Let the bot's messages speak.
- Speed up anything that takes longer than 6 seconds using Screen.studio's time-warp (at 2x). Judges don't need to watch a 20-second pause.
- One cut maximum during this segment. No jump cuts every 2 seconds.

---

## 5. Voiceover script (draft, ~280 words)

This is a draft. Kene owns the final. Timing budgeted at ~2.5 words per second of voice.

```
[0:00-0:15 - Opening over title card]
"Over the last 18 months on a Graduate visa, I applied to more than
80 UK jobs. Almost half of them, turns out, were ghost postings.
The rest wanted salaries below the sponsorship threshold, or
companies not even on the UK Sponsor Register. I built Trajectory
because the AI job-search tools out there were making the problem
worse."

[0:15-0:45 - Friend recommends job, user forwards to bot]
"A friend sends me a job. Looks fine on paper. Instead of burning
three hours tailoring a CV, I forward it to Trajectory."

[0:45-1:20 - 8 agents fan out, verdict arrives]
"Eight Opus 4.7 sub-agents run in parallel. They scrape the company
surface, check Companies House, cross-reference the Sponsor Register
and SOC going rates, score ghost-job probability, and compare salary
data from three sources. In 30 seconds they've done what a human
would take four hours to do properly."

[1:20-1:40 - Expanded verdict]
"Verdict: don't apply. Three hard blockers, each cited to gov.uk or
Companies House or public review data. Every claim is clickable.
Nothing invented."

[1:40-2:15 - Salary moment]
"Later I ask about salary for another role I'm actually considering.
Trajectory knows my situation — the visa timeline, recent rejection
count, the market data for this role in London — and pitches an
opening number grounded in all of it. Plus the exact words to use
when the recruiter asks."

[2:15-2:20 - Transition to live]
"Here it is live."

[2:20-3:00 - Live footage]
(No voiceover. Let the bot speak.)
```

Record voiceover on a quiet room, phone in airplane mode, recorded on a decent mic or the laptop's built-in. Do 3 takes. Pick the one where you sound like you.

---

## 6. Quick decisions to avoid perfectionism

Set these once, don't debate them on Sunday:

| Decision | Choice |
|----------|--------|
| Light or dark? | Light mode for title/closing cards, dark mode for the chat mockups (more aesthetic contrast) |
| Resolution | 1920×1080 final, 1080×1920 mockups up-scaled to fit |
| Frame rate | 30fps |
| Audio | Voiceover only, no music |
| Captions | Yes, burned in. Use the voiceover script. Improves accessibility + judges can watch muted |
| Credits / logo | Minimal. No Anthropic logo, no sponsor logos. |
| Export | mp4, h.264, 8-12 Mbps |
| Upload | YouTube unlisted (follows every prior winner's pattern) |

---

## 7. Claude Design known strengths and limits (as of April 2026)

**Strengths (use these):**
- Static UI mockups with instructions on content and aesthetic
- One-page layouts, pitch deck slides, one-pagers
- Extracting a design system from a codebase (not needed here)
- Landing page mockups

**Limits (don't fight them):**
- Precise motion/animation control — it's not built for frame-by-frame animation
- Audio syncing — not its domain
- Complex video timelines — use a proper editor

If Claude Design produces something slightly off:
- Paste the output back and ask for one specific change ("Make the bot avatar smaller and in the top-left of the bubble").
- Iterate ~3 times per frame max. After that, fall back to manual editing.

---

## 8. Backup plan if Claude Design is unavailable on Saturday

If the Design tab is rolled out slowly and isn't accessible when you need it:

1. Use Figma Community templates for iMessage and Telegram mockups (search "iMessage template", "Telegram chat UI").
2. Edit in Figma — change text, colours, spacing.
3. Export PNGs.
4. Same workflow from there.

Don't block on Claude Design being the tool. The important thing is the aesthetic consistency, not the tool used.

---

## 9. Time budget for video production

Sunday afternoon (target 4:00pm finish, submission 1:00am Monday BST):

| Block | Hours |
|-------|-------|
| Record real-footage segment | 0.75 |
| Generate all Claude Design frames | 1.5 |
| Record voiceover (3 takes + pick best) | 0.5 |
| Edit in timeline (cross-fades, voiceover sync, captions) | 2.5 |
| Export, watch end-to-end, re-record any obvious mistakes | 1.0 |
| Upload to YouTube, get unlisted URL | 0.25 |
| **Total** | **~6.5 hours** |

Start by 10:00 AM Sunday. If by 4:00 PM you haven't finished, stop polishing — ship the rough cut, submit, then resubmit if they allow updates.

---

## 10. What a winning video looks like

From reviewing last round's winners (CrossBeam, Elisa, PostVisit, TARA, Conductr):

1. **Founder speaks early.** You on camera or in voiceover in the first 15 seconds, saying why you built it.
2. **One memorable number.** The "third of UK jobs are ghost" stat, or "£X saved per application", or "4 hours → 30 seconds".
3. **Live proof.** At some point, real code runs. Real numbers appear. A clickable citation opens a real URL.
4. **Tight closing.** No rambling credits. Product name, URL, thanks, cut.
5. **Under the cap.** A 2:50 video reads more confident than a 3:00 one that used every second.
