"use strict";
/* renderResult and busy — the verbal panel's own output, RUN rather than read.
 *
 * WHY EXECUTED. What this function gets wrong, it gets wrong in the sentence it prints, and there
 * is no way to read a sentence out of a source file: the markup is assembled from six branches, an
 * escaper, a label table and a fallback chain, and the only honest check is to hand it a server
 * response and read what came out.
 *
 * THE ONE THAT MATTERS. The server's evidence gate accepts a flag when the model's quote is
 * verbatim in the transcript — correctly, because that proves the words were SAID. It does not
 * prove they meant the flag. "It is not a hard bid" contains the words "a hard bid". The panel used
 * to print that crop after the word "because", so a transcript that said no ended up on screen as
 *
 *     Hard bid on — because you said: "a hard bid"
 *
 * which asserts the reverse of what the estimator told it, over their own signature. The server now
 * sends `context` INSTEAD of `quote` — the transcript's own words either side of the match — so the
 * "not" is on screen next to the switch. Every scenario below that renders a flag checks the WORDS,
 * not just that a <span> exists.
 *
 * AND THE HALF THE SERVER CANNOT DO. Its matcher requires consecutive tokens, which cannot tell
 * that "not local hard bid" is a genuinely consecutive run ACROSS a full stop. backend's own
 * test_a_quote_cannot_be_stitched_across_a_full_stop leaves that to be judged by a person, so this
 * display is the safeguard: a multi-sentence excerpt has to be unmissable, not one grey line.
 *
 * Usage: node verbal-render-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "polish-verbal.js"), "utf8")
  .replace(/\r\n/g, "\n");

/** Lift a named function out of the panel's IIFE (two-space indent), braces balanced. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from polish-verbal.js — rewrite this harness");
  const open = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error(what + " is gone from polish-verbal.js — rewrite this harness");
  return m[0];
}

/** Only the nodes this function touches: the output box, the transcript box, and the two buttons
 *  busy() reaches for. Ids come from frontend/polish-intake.html and are load-bearing. */
function makeDom() {
  const nodes = {};
  function node(id) {
    let html = "";
    const self = {
      id, value: "", hidden: true, disabled: false, textContent: "", listeners: [],
      get innerHTML() { return html; },
      set innerHTML(v) {
        html = String(v);
        // The rendered markup's own ids become findable, which is the point: busy() looks for
        // #verbal-answer-go, an element renderResult writes rather than one the page ships.
        let m;
        const re = /id="([\w-]+)"/g;
        while ((m = re.exec(html))) { nodes[m[1]] = nodes[m[1]] || node(m[1]); }
      },
      addEventListener(type, handler) { self.listeners.push({ type, handler }); },
    };
    return self;
  }
  return { el: (id) => (nodes[id] = nodes[id] || node(id)), nodes };
}

function build() {
  const dom = makeDom();
  dom.el("verbal-go").textContent = "Fill the form";     // as polish-intake.html ships it
  dom.el("verbal-text").value = "";
  const runs = [];
  const scope = new Function("$", "runs", `
    "use strict";
    ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
    ${grab(/^  var FIELD_LABELS = \{[\s\S]*?\n  \};$/m, "FIELD_LABELS")}
    ${grab(/^  var GO_LABEL = [^\n]*$/m, "GO_LABEL")}
    ${grab(/^  var ASK_LABEL = [^\n]*$/m, "ASK_LABEL")}
    var asked = false;
    function run() { runs.push(1); }
    ${fn("label")}
    ${fn("busy")}
    ${fn("sentencesOf")}
    ${fn("evidenceHtml")}
    ${fn("renderResult")}
    return { renderResult: renderResult, busy: busy, evidenceHtml: evidenceHtml,
             GO_LABEL: GO_LABEL, ASK_LABEL: ASK_LABEL,
             setAsked: function (v) { asked = v; } };
  `)(dom.el, runs);
  return { dom, scope, runs };
}

/** One render. Returns the markup plus the pieces a person would actually look at. */
function render(res, applied, opts) {
  const b = build();
  if (opts && opts.asked) b.scope.setAsked(true);
  b.scope.renderResult(res, applied);
  const html = b.dom.nodes["verbal-out"].innerHTML;
  return {
    html,
    hidden: b.dom.nodes["verbal-out"].hidden,
    // Every group, by its heading, with the list items under it as plain text.
    groups: html.split('<div class="vgroup').slice(1).map((chunk) => {
      const extraClasses = (/^([^>]*)>/.exec(chunk) || ["", ""])[1].replace(/"/g, "").trim();
      // Everything under the heading, the heading itself excluded — a group's copy is what the
      // estimator reads after they know which group they are in.
      const body = chunk.replace(/^[\s\S]*?<\/h3>/, "");
      return {
        cls: extraClasses,
        heading: (/<h3>([^<]*)<\/h3>/.exec(chunk) || [])[1] || null,
        items: (chunk.match(/<li>[\s\S]*?<\/li>/g) || [])
          .map((li) => li.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()),
        text: body.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(),
      };
    }),
    quotes: html.split('<span class="vq').slice(1)
      .map((c) => c.replace(/^[^>]*>/, "").split("</span>")[0].replace(/\s+/g, " ").trim()),
    hasAskBox: /id="verbal-answer-go"/.test(html),
    askLabel: b.scope.ASK_LABEL,
  };
}

const out = {};

// ═══ 1. THE FLAG THAT WOULD HAVE LIED ════════════════════════════════════════
// The estimator said it is NOT a hard bid. The model quoted "a hard bid", which is verbatim, so the
// server accepted it. What goes on screen has to be the sentence, not the crop.
out.negatedQuote = render(
  { conditions: { hard_bid: {
      value: true,
      context: "the district told us it is not a hard bid this time around",
  } } },
  { filled: [], applied: ["hard_bid"], respected: [] });

// ═══ 1b. THE ONE THE SERVER CANNOT CATCH ════════════════════════════════════
// The matcher requires consecutive tokens, which kills the mid-word match. It cannot tell that
// "not local hard bid" is a legitimately consecutive run ACROSS a full stop — the words really are
// in that order. backend/verbal_intake.py leaves that to be judged by a person, so the boundary has
// to be impossible to skim past.
out.acrossASentence = render(
  { conditions: { hard_bid: {
      value: true,
      context: "Olathe fire station on Ridgeview. It is not local. Hard bid though.",
  } } },
  { filled: [], applied: ["hard_bid"], respected: [] });
out.twoSentences = render(
  { conditions: { local: {
      value: false,
      context: "It is not local. Hard bid though",
  } } },
  { filled: [], applied: ["local"], respected: [] });

// ═══ 2. no context came back ════════════════════════════════════════════════
// `context` is a str, never absent and never empty on an accepted condition — so this is the
// malformed-response path only: a rolled-back server, a truncated body, a field that arrives blank.
// There is deliberately no `quote` fallback; the backend stopped sending one. An empty pair of quote
// marks would read as "the estimator said nothing", which is the one thing the gate already proved
// false, so it says what happened in words instead.
out.noContext = render(
  { conditions: { prevailing_wage: { value: true } } },
  { filled: [], applied: ["prevailing_wage"], respected: [] });
out.emptyContext = render(
  { conditions: { prevailing_wage: { value: true, context: "   " } } },
  { filled: [], applied: ["prevailing_wage"], respected: [] });
// A dead `quote` on the wire must not be resurrected as evidence: it is the model's crop, which is
// the whole reason the field was removed.
out.staleQuoteOnly = render(
  { conditions: { taxable: { value: false, quote: "tax exempt" } } },
  { filled: [], applied: ["taxable"], respected: [] });

// ═══ 4. the switches the estimator set themselves ═══════════════════════════
out.respected = render(
  { conditions: { hard_bid: {
      value: true,
      context: "the district told us it is not a hard bid this time around" } } },
  { filled: [], applied: [], respected: ["hard_bid"] });

// ═══ 5. the filled fields, and the whole panel at once ══════════════════════
out.filled = render(
  { fields: { project_name: "Blue Valley West", city: "Overland Park" },
    conditions: { prevailing_wage: {
      value: true, context: "the district says prevailing wage on this one" } },
    unsupported: ["remodel_tax"],
    missing: ["bid_date", "remodel_tax"],
    question: "When is the bid due?" },
  { filled: ["project_name", "city"], applied: ["prevailing_wage"], respected: [] });

// ═══ 6. an older applyVerbal that returns no `respected` at all ═════════════
// The two files ship separately in the browser cache. A missing key must not throw.
out.noRespectedKey = render(
  { conditions: { local: { value: false,
                           context: "no it is out of town about ninety miles" } } },
  { filled: [], applied: ["local"] });

// ═══ 7. an empty extraction still says something ════════════════════════════
out.nothing = render({}, { filled: [], applied: [], respected: [] });

// ═══ 8. the transcript's words are ESCAPED ══════════════════════════════════
// A transcript is typed by a person and a context string is assembled by the server out of it.
// Neither is markup.
out.escaping = render(
  { conditions: { taxable: { value: false,
                             context: '<script>alert("x")</script> they are tax exempt' } } },
  { filled: [], applied: ["taxable"], respected: [] });
// The multi-sentence branch builds its markup a different way. Both have to escape, and only a
// fixture that crosses a boundary reaches the second one.
out.escapingAcrossSentences = render(
  { conditions: { taxable: { value: false,
      context: 'They are tax exempt. <img src=x onerror="alert(1)"> the district said so' } } },
  { filled: [], applied: ["taxable"], respected: [] });

// ═══ 9. busy() reaches the follow-up button too ═════════════════════════════
// #verbal-answer-go is rendered INTO the output box, and it is the button in front of the estimator
// while the second run is in flight. Left live, one double click spends the third of three
// rate-limited runs.
{
  const b = build();
  b.scope.renderResult({ question: "When is the bid due?" },
                       { filled: [], applied: [], respected: [] });
  const go = () => b.dom.nodes["verbal-go"];
  const ask = () => b.dom.nodes["verbal-answer-go"];
  const snap = () => ({ go: { disabled: go().disabled, text: go().textContent },
                        ask: { disabled: ask().disabled, text: ask().textContent } });
  b.scope.busy(true);
  const during = snap();
  b.scope.busy(false);
  out.busy = { during, after: snap(), askLabel: b.scope.ASK_LABEL,
               goLabel: b.scope.GO_LABEL };
}

// ═══ 10. the follow-up appends to the transcript and runs once ══════════════
// Unchanged behaviour, pinned because busy() now touches the same button: a disabled button whose
// handler still fires is the same double spend by another route.
{
  const b = build();
  b.dom.el("verbal-text").value = "Blue Valley West in Overland Park";
  b.scope.renderResult({ question: "When is the bid due?" },
                       { filled: [], applied: [], respected: [] });
  b.dom.nodes["verbal-answer"].value = "  due the third of September  ";
  const click = b.dom.nodes["verbal-answer-go"].listeners
    .filter((l) => l.type === "click")[0].handler;
  click();
  out.followUp = { transcript: b.dom.nodes["verbal-text"].value, runs: b.runs.length };
  // A blank answer is not an answer, and must not spend a run.
  b.dom.nodes["verbal-answer"].value = "   ";
  click();
  out.followUp.runsAfterBlank = b.runs.length;
}

// ═══ 11. the question is not asked twice ════════════════════════════════════
out.askedAlready = render({ question: "When is the bid due?" },
                          { filled: [], applied: [], respected: [] }, { asked: true });

// ═══ 12. `quote` is never read again, anywhere in the panel ═════════════════
// The backend removed the field. A resurrected read would render "undefined" beside a price flag,
// or worse, quietly reintroduce the model's crop as the evidence on screen.
out.sourceReadsQuote = /\.quote/.test(SRC);

// ═══ 13. the word "because" is gone from the whole file ═════════════════════
// It was the frame that turned a report of what was said into a claim about why. Checked over the
// SOURCE as well as the output, because a second branch could reintroduce it where no fixture looks.
out.sourceHasBecause = /because you said/i.test(SRC);

console.log(JSON.stringify(out));
