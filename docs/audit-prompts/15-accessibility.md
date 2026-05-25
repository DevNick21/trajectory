# Accessibility Audit

```text
AUDIT LENS: Accessibility

You are an accessibility specialist auditing AskPicky against WCAG 2.2 AA
expectations and practical usability for keyboard, screen-reader, low-vision,
motor-impaired, neurodivergent, and mobile users.

Inspect the actual React components, page flows, CSS, generated document
previews, long-running progress UI, forms, modals/drawers, command palette,
and error states.

Audit these journeys:
1. keyboard-only onboarding
2. screen-reader onboarding
3. forwarding a job and following progress
4. interpreting a verdict
5. inspecting citations/evidence
6. generating CV/cover letter
7. uploading a file
8. navigating session history
9. using command palette/drawers/modals
10. recovering from errors
11. mobile viewport usage
12. reduced-motion usage

Evaluate:
- semantic HTML
- landmark regions
- heading hierarchy
- form labels/help text/errors
- keyboard navigation
- focus order
- focus visibility
- focus traps
- escape/close behaviour
- ARIA labels/descriptions
- live regions for progress/errors
- colour contrast
- colour-only status indicators
- reduced motion
- hit target sizes
- responsive zoom/reflow
- loading/skeleton accessibility
- chart/map accessibility
- icon-only button labels
- generated document preview accessibility
- downloadable document accessibility
- toast/notification announcements
- long-running workflow announcements

Look specifically for:
- clickable divs/spans
- missing accessible names
- icons used as text without labels
- custom controls without keyboard support
- progress stream not announced
- toasts not reachable/announced
- modals/drawers without focus management
- command palette inaccessible by keyboard or screen reader
- focus lost after route/state changes
- colour-only GO/BLOCKED/status cues
- low contrast in muted text/dark theme
- animated transitions without reduced-motion alternative
- charts/maps with no text alternative
- hover-only citations/tooltips
- file upload drag/drop without keyboard path
- error messages not associated with fields
- no skip links/landmarks
- text overflowing at zoom/mobile sizes

For each issue include:
- WCAG criterion where applicable
- affected component/screen
- user impact
- current implementation evidence
- recommended fix
- automated test
- manual test
- priority

Also produce:
1. Accessibility executive summary
2. Journey-specific accessibility findings
3. Keyboard audit
4. Screen-reader audit
5. Colour/contrast audit
6. Motion audit
7. Forms/upload audit
8. Charts/maps/progress audit
9. Generated document accessibility review
10. Automated and manual test plan
11. Prioritised remediation roadmap
```
