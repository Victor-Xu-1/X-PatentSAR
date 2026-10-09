# Product craft and acceptance

X-PatentSAR uses restrained biomedical-workbench presentation: original documents,
structures, raw measurements and the user's next action take priority over technical
metadata. Award and commercial quality are design targets, not certification claims.
The reference article's private algorithms are not represented as reproduced.

## One visual and interaction authority

- `frontend/src/styles/tokens.css` owns theme values. Feature styles own their layout;
  `product-craft.css` applies the shared page/dialog rhythm, not another theme.
- Existing components own dialogs, table queries, column selection, source navigation,
  language persistence, private settings and drawing edits. No parallel UI controller.
- Source identifiers, chemistry, values, units and user titles never change with the
  interface language. English is the fresh-visit default; saved choices are retained.
- Complete SAR results start at results, with intake collapsed. Intake drafts remain
  mounted and are revealed only by an explicit action or a new dataset context.
- SAR tasks use three concise milestones: data, activity, analyze. Activity choices
  precede the review/run step. Back and language changes preserve drafts; only the
  existing explicit submit creates a study. Regions remain optional, not a second queue.
  A persistent result workbench returning to the same dataset without a job must
  reveal setup from the current route, not its first-mounted disclosure state.
- Activity selection shows the actual selectable count up to the existing eight
  context limit. Small lists use two columns where space permits. Equal molecule
  and observation counts are shown once; unequal counts remain explicit. Raw
  context, repeat information and original IDs remain unchanged and accessible.
- The report title, actual job state, historical scope and research-only meaning
  share one compact header. Full explanations live in existing details, not a
  second status block. Result views form a single horizontally scrolling row;
  programmatic card-to-table navigation reveals its active control without
  scrolling the document or taking focus. Navigation never starts a study.
- Recent-file rows stack metadata and actions before titles become cramped at
  intermediate widths. Source title, availability, acceptance and timestamp stay
  visible and associated with the same keyboard-operable open button.
- Result previews prioritize structures, measured values, distributions and tables.
  One details dialog owns technical counts, source QA and limitations. Candidate
  cards show chemistry, raw activity and six properties; provenance stays available
  through source selection. A single format selector preserves all four exports.
- The SAR activity table starts with one search/columns/options toolbar. Secondary
  filters and sorting are disclosed explicitly; hiding options preserves their
  controlled values and shows the active-option count. Reset changes only those
  filters/sort, not the source search or column visibility. Existing server-side
  query, paging and complete-report export authorities remain unchanged. Preview
  cells are centered; generic pair-table alignment cannot override study tables.
- A region click selects a recorded region. Modification preview reads a published
  strict comparison and rechecks its immutable full graph and attachment mapping.
  It does not design a molecule, rerun extraction or call a model.
- Raw measurements, computed properties and captured predictions remain separate.
  Grade/interval overlap, missing context and unrepresentable differences stay unknown.
  Hidden technical detail does not remove source links, issues or acceptance boundaries.
- Compact workflow labels remain legible in both languages; full stage meaning,
  actual states and recorded execution order stay in the same model and disclosure.
- Environment readiness distinguishes unknown/stale checks from verified readiness
  and known missing paths. The currently available next action receives emphasis;
  no presentation shortcut enables installation or turns path presence into readiness.
- Local MDL conversion is a bounded, CSRF-authenticated read despite HTTP POST.
  Read failures never imply that a correction was saved. Actual writes with server
  faults or unreadable successful bodies stay uncertain, without automatic replay.
  Filtered downloads use the same 128 MiB export bound as unfiltered downloads.
- The correction canvas fits the loaded structure after its native render is
  available and when its dimensions change. An explicit fit control restores
  that view after manual zoom/pan. The viewport module changes only renderer
  zoom/viewBox, never atom coordinates, graph identity, descriptors, or saved
  corrections; it does not export/revalidate on resize. Resize notifications
  are coalesced into one animation frame and disposed with the editor. The
  native minimum zoom is preserved, with manual pan/zoom retained for extremes.
  Fitting also publishes the native micro-editor zoom-feedback event, so the
  displayed percentage matches the actual SVG viewBox scale rather than an
  earlier toolbar state. Feedback never uses the drawing-change/export channel.

## Required page/module/state matrix

Keep current evidence outside source trees, indexed by revision, installed-wheel
identity, source task identity, viewport, language and state. Do not accept a loading
screen as the finished page. A screenshot alone proves neither computation nor a save.

| Surface | Modules and interactions | States to inspect |
| --- | --- | --- |
| Shared shell | direct navigation, language selector, skip link, version, project return | fresh English, saved language, narrow navigation, focus and active route |
| PDF intake | file chooser/drop target, selected PDF, submit state | empty, selected, invalid, busy, recoverable error; no implied job creation |
| Recent files | source list, acceptance marker, open action, recoverable deletion | populated, empty, paged, deletion confirmation, conflict/error |
| Tasks | current stage, compact progress, pause/cancel/resume, history actions | pending, running, complete, failed, interrupted, retained history |
| Main workspace | original/text/annotation tabs, page tools, draggable split, collapse/fullscreen | genuine loaded PDF/crops, source focus, narrow stack, keyboard resize |
| Result table | original IDs, structure, Lead, individual assays, six properties, paging | no-activity rows retained, sticky IDs, wide scroll, empty search, loading/error |
| Spreadsheet controls | column visibility, value/condition/color filters, sort, resize, copy/export | selected values, cleared filters, hidden/restored columns, keyboard/pointer focus |
| Structure details | original crop, current redraw, raw structure identity | loaded/absent/invalid drawing, source-owned stereochemistry, close/focus restore |
| Online correction | Ketcher bridge, original ID, activity and property fields, save | initialized, edited, validation, conflict, uncertain write recovery, saved reread |
| Environment | complete setup, component status, storage dialog | real untested/present/ready states, disabled capability, explicit install consent |
| Private LLM settings | API configuration, consent, key replacement, synthetic test | disabled/unconfigured, nonsecret draft, validation/conflict, no unsolicited call |
| Evidence summary | counts, measured assay records, source links, issues | loaded, no data, genuine error, collapsed technical detail |
| SAR intake | extracted snapshot, CSV preview and explicit column mapping | new intake, complete-result route, preserved draft, validation/import conflict |
| SAR setup | guided activity/review steps, context/policy selection, original reference, atom/port selection | unselected/continue disabled, back/draft/focus preservation, named multi-regions, saved region, ambiguous/invalid selection |
| SAR overview | independent counts and distributions, counting units | source rows vs eligible molecules vs observations, grades/intervals, missing values |
| SAR scaffolds | descriptive cores and members, original structures | one/multiple cores, paging, original-source selection; not strict proof by itself |
| SAR candidates | raw measured contexts, six captured properties, prediction provenance | real candidates, tied evidence, missing/predicted facts, no fabricated score |
| SAR regions | atom-coordinate map, region selector, fragments, exact modification preview | selected/changed/no-variation, support/counterexample, actual graph pair/data delta |
| SAR activity table | selected-context columns, source IDs, properties, filters and export | long/short table, paging, missing activity, hidden columns, source callback |
| SAR source and lifecycle | immutable source, contextual detail, warnings, export and resume | historical/stale/complete/error, canceled/interrupted, original data preserved |

## Verification boundaries

Publication-grade readability follows the principles in
[Nature's figure specifications](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/)
and [panel guidance](https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/):
clear units, original labels, restrained colors with redundant meanings, sufficient
structure space, consistent type, honest counts and no ornamental chart shadows.
Physical manuscript point sizes are not applied to screen UI. This is not a claim
that a browser screenshot satisfies a particular journal's editable-artwork submission.
Strength captions come from captured study policy, never guessed patent thresholds;
an absent rule is unclassified, not observed zero strong activity.
The shared passive-SVG viewer applies readable variants of the stock O/F/Cl
palette after validation. This affects display color only: source SVG, atom/bond
geometry, labels, indices, stereochemistry, region coordinates and immutable reports
are not rewritten. Unknown colors remain unchanged and unsafe SVG remains rejected.
The same RDKit drawing authority uses a 360 by 240 display canvas for recorded
fragments and descriptive cores, so port labels and small substituents remain
legible in compact cards. Full molecule drawings and atom-selection maps retain
their 1000 by 800 canvas, immutable atom order and normalized overlay coordinates.
Fragment composition is one 12-pixel horizontal strip, with no later competing
height override. Drawing requests never revise structures, reports or measurements.
The conservative content-bound SAR engine still invalidates interrupted older
engine checkpoints after code changes; completed historical reports remain readable.

Run only explicit changed-module and direct-consumer checks from
`.github/verification_scope.json`. Browser writes use isolated controller-owned
fixtures or copies, never production tasks. Real completed tasks are used read-only
for rendered source/result consistency and scientific-boundary checks. Provider calls,
scientific reruns and environment installs require their own authority and evidence.

Record observed defects and repeat their focused checks. Publish only after the PR
is merged and the exact mainline wheel is deployed, with retained rollback material.
Keep unvisited states, external scientific acceptance and commercial usability testing
explicitly outstanding; do not replace them with a static-build success or award claim.
