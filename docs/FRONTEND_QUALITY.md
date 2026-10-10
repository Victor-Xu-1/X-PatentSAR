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
  Project intake starts with the source and one Continue action; the optional
  custom title is retained in a native disclosure. Existing snapshot identity,
  default source title, uncertain-write protection and explicit submission stay
  unchanged; revealing the name field never creates a dataset or task.
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
  Known overview/region strength rules share the existing context/matching disclosure,
  rather than repeating an explanatory row above each preview. Unclassified or
  ambiguous strength remains visible and is never presented as a measured zero.
  The guided activity selector uses its labelled direction input for the empty
  draft; invalid grade-order feedback and disabled continuation remain intact.
  Structure detail opens on the original crop and explicitly non-original redraw;
  raw SMILES starts collapsed, remains verbatim, and retains its disclosure state
  across language changes. Primary/secondary original-source links share one URL
  resolver and never invent a page. Full extraction caveats stay in existing
  validation detail and on the redraw caption, while actionable image/chemistry
  failures remain visible. Frame errors with explicit UI provenance localize;
  untagged raw SDK/server diagnostic messages remain untouched.
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
  In the wide two-column explorer, the reference viewport itself stays alongside
  the chosen modification and its measurements. Its bounded native scrolling
  contains one or multiple reference graphs; an inner card is not a competing
  sticky/scroll owner. Narrow layouts restore ordinary document flow. Keyboard
  access is exposed only for real overflow, with coalesced/disposed resize work;
  reference loading/locale changes never move focus or rerun a drawing provider.
  Pointer outlines are visible only during interaction, not a duplicate permanent
  circle around every atom. The existing region palette remains their authority.
  The active region has a stronger keyline and tint; other regions remain visible.
  Original atom coordinates and region membership never change with selection.
  Hover/focus hotspots emphasize their region-coloured outline only: their
  transparent centers must not cover element letters or stereochemical marks.
  Inactive region labels retain readable contrast while the current keyline
  and tint remain distinct. Pointer feedback uses the same colour assignment,
  not an overriding border authority or another drawing layer.
  Atom hotspots stay pointer targets while the adjacent named legend owns one
  keyboard control per region, rather than duplicating each atom in Tab order.
  An explicit preview click reveals and focuses its inline comparison using the
  shared reduced-motion preference. Repeating that click reveals the same view,
  without replaying its API computation. Refresh, language changes and returning
  to a hidden view do not steal focus or scroll again. Close returns to the exact
  originating fragment, including while the preview is loading or failed.
  When asynchronous content extends the document's initial scroll limit, only
  that explicit request may settle its view once; a user who has moved to another
  control is never pulled back. Native installed-browser checks verify the
  comparison's final visible position, not just its programmatic focus.
  Fragment cards use a compact labelled comparison-count group, not a sentence,
  normalized share or inferred score. Zero, unknown and missing counts stay distinct.
  Current conservation reports show only the displayed fragments' nonempty legend
  categories; colours retain their complete original-domain index. Full ranges stay
  in matching detail and historical observation charts keep their recorded scope.
  Shared inline-selection reveal owns result tabs and both region selectors; resize
  work is animation-frame coalesced and disposed, without page scroll or focus changes.
  Narrow previews retain table/row/header semantics while putting both raw values
  and their backend change result in the visible width. Source IDs and unit labels
  use existing captured data and the shared context-label presentation authority.
  Molecular comparisons offer a small read-only enlargement control after their
  current safe drawing has loaded and been validated. The existing modal reuses
  exactly that passive RDKit image, with bounded 100–400% fit-relative display
  magnification, Fit and native overflow scrolling. No second renderer, graph
  parsing, molecule editing, provider call or drawing request is introduced.
  Failed/inactive/stale identities cannot open or revive an inspector. Closing
  restores its originating control; raw identifiers and images survive locale
  changes. Shared inline reveal also keeps the current header module visible.
  At Fit the entire passive image frame must be contained by the definite canvas
  dimensions: intrinsic grid minimums must not enlarge it beyond the viewport.
  Inspect actual large source molecules as well as small controlled graphs;
  passing scalar zoom checks alone does not prove full-structure containment.
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
