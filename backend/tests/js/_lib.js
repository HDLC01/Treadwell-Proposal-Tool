"use strict";
/* Shared helpers for NEW node harnesses in backend/tests/js.
 *
 * WHY ONE FILE. Thirty-odd harnesses in this folder each carry their own copy of the same five
 * helpers (a CRLF-normalising read, a brace matcher, a function lifter, a regex grab, a tag
 * stripper) and the copies have drifted: one matcher counts braces inside strings, one lifter
 * needs the function at a fixed indent, one tag stripper takes a single pass. The v2 estimating
 * program writes many new harnesses, and every one of them lifts pieces of the page it is about
 * to refactor, so the helpers get their own file, their own tests (test_harness_lib_js.py runs
 * lib-selftest-harness.js), and ONE behaviour.
 *
 * EXISTING HARNESSES ARE NOT RETROFITTED. They are pinned by tests that read them as they are,
 * and a harness that works is not edited for tidiness. Use this file from new harnesses only.
 *
 * WHAT IS HERE
 *   read(path)                      the file as text, every line ending LF
 *   balanced(src, open)             index of the bracket that closes the one at `open`
 *   grab(src, re, what)             the first regex match, or a loud failure
 *   liftSource(src, name, opts)     the text of `function name(...) {...}`
 *   lift(src, name, deps, opts)     that function, bound to `deps` BY NAME
 *   grabConst(src, name, opts)      the text of `const|let|var name = ...;`
 *   stripTags(html)                 the text of some markup, tags and comments removed
 *   stringLiterals(src)             every string and template text in some JavaScript, as
 *                                   { text, line }, comments and regex literals left out
 *   escapeRegExp(text), reOf(text)  the only way to put a variable into a regex
 *
 * THE RULE FOR LIFTED CODE: a function lifted by name runs in a scope that holds ONLY what the
 * harness hands it in `deps`. A callee the harness forgot is an unbound identifier inside the
 * lifted copy, a ReferenceError at run time, which is the failure that took the board down on
 * prod on 2026-08-12. So a new helper that a lifted function calls goes into a CORE module (which
 * the harness loads whole) and not into the page file, and lift() throws rather than guessing.
 */
const fs = require("fs");

const NL = "\n";

/** A file as text with every line ending normalised to LF (and no byte-order mark).
 *
 *  Git hands these files out CRLF on a Windows checkout and LF everywhere else, and a harness
 *  that matches source text with a pattern anchored on a newline sees a stray carriage return
 *  between the brace and the newline it is looking for. CI stays green while a developer's
 *  machine reports a wall of "the harness crashed", which is the worst possible split. */
function read(p) {
  return fs.readFileSync(p, "utf8").replace(/^﻿/, "").replace(/\r\n/g, NL);
}

// ── a bracket matcher that knows what code is ────────────────────────────────
const CLOSER = { "{": "}", "(": ")", "[": "]" };
// After one of these a `/` starts a regular expression; after anything else it divides.
const REGEX_AFTER_CHAR = "(,=:[!&|?{};+-*%<>~^";
const REGEX_AFTER_WORD = new Set(["return", "typeof", "instanceof", "in", "of", "new", "delete",
  "void", "throw", "case", "do", "else", "yield", "await"]);

function isIdentStart(c) { return (c >= "a" && c <= "z") || (c >= "A" && c <= "Z") || c === "_" || c === "$"; }
function isIdentPart(c) { return isIdentStart(c) || (c >= "0" && c <= "9"); }
function isSpace(c) { return c === " " || c === "\t" || c === "\n" || c === "\r" || c === "\f" || c === "\v"; }

/** After the quote at `i`, the index just past its closing quote. */
function skipQuoted(src, i) {
  const q = src[i];
  let j = i + 1;
  while (j < src.length) {
    const c = src[j];
    if (c === "\\") { j += 2; continue; }
    if (c === q) return j + 1;
    j++;
  }
  throw new Error("unterminated " + q + " string starting at " + i);
}

/** After the regular-expression literal at `i`, the index just past its flags. */
function skipRegex(src, i) {
  let j = i + 1;
  let inClass = false;
  while (j < src.length) {
    const c = src[j];
    if (c === "\\") { j += 2; continue; }
    if (c === "\n") break;
    if (inClass) { if (c === "]") inClass = false; }
    else if (c === "[") inClass = true;
    else if (c === "/") {
      j++;
      while (j < src.length && isIdentPart(src[j])) j++;
      return j;
    }
    j++;
  }
  throw new Error("unterminated regular expression starting at " + i);
}

/** After the template literal at `i` (its opening backtick), the index just past the closing one.
 *  A `${ ... }` substitution is code, so it is scanned as code and may hold braces, strings and
 *  further template literals of its own. */
function skipTemplate(src, i) {
  let j = i + 1;
  while (j < src.length) {
    const c = src[j];
    if (c === "\\") { j += 2; continue; }
    if (c === "`") return j + 1;
    if (c === "$" && src[j + 1] === "{") { j = scan(src, j + 2, "}") + 1; continue; }
    j++;
  }
  throw new Error("unterminated template literal starting at " + i);
}

/** Scan code from `i` until the unmatched `stop` character, and return its index. Strings,
 *  template literals, comments and regular-expression literals are skipped whole, so a brace
 *  inside any of them never counts. */
function scan(src, i, stop) {
  const stack = [];
  let prev = "";          // the last significant character, to tell a regex from a division
  let word = "";          // the identifier that ends at `prev`, for `return /x/`
  while (i < src.length) {
    const c = src[i];
    if (isSpace(c)) { i++; continue; }
    if (c === "'" || c === '"') { i = skipQuoted(src, i); prev = "a"; word = ""; continue; }
    if (c === "`") { i = skipTemplate(src, i); prev = "a"; word = ""; continue; }
    if (c === "/") {
      const n = src[i + 1];
      if (n === "/") { const e = src.indexOf(NL, i); i = e < 0 ? src.length : e; continue; }
      if (n === "*") {
        const e = src.indexOf("*/", i + 2);
        if (e < 0) throw new Error("unterminated comment starting at " + i);
        i = e + 2;
        continue;
      }
      if (prev === "" || REGEX_AFTER_CHAR.indexOf(prev) >= 0 || (prev === "a" && REGEX_AFTER_WORD.has(word))) {
        i = skipRegex(src, i);
        prev = "a"; word = "";
        continue;
      }
      prev = "/"; word = ""; i++;
      continue;
    }
    if (c === "{" || c === "(" || c === "[") { stack.push(CLOSER[c]); prev = c; word = ""; i++; continue; }
    if (c === "}" || c === ")" || c === "]") {
      if (!stack.length) {
        if (c === stop) return i;
        throw new Error("unbalanced " + c + " at " + i);
      }
      const want = stack.pop();
      if (c !== want) throw new Error("expected " + want + " but found " + c + " at " + i);
      prev = c; word = ""; i++;
      continue;
    }
    if (isIdentStart(c) || (c >= "0" && c <= "9")) {
      let j = i + 1;
      while (j < src.length && isIdentPart(src[j])) j++;
      word = src.slice(i, j);
      prev = "a";
      i = j;
      continue;
    }
    if (c === ";" && stop === ";" && !stack.length) return i;
    prev = c; word = ""; i++;
  }
  throw new Error("ran off the end of the source looking for " + stop);
}

/** The index of the bracket that closes the one at `open` (a `{`, `(` or `[`). */
function balanced(src, open) {
  const o = src[open];
  if (!Object.prototype.hasOwnProperty.call(CLOSER, o)) {
    throw new Error("balanced() needs an opening bracket at " + open + ", found " + JSON.stringify(o));
  }
  return scan(src, open + 1, CLOSER[o]);
}

// ── lifting the real source ──────────────────────────────────────────────────
/** The first match of `re` in `src` (the whole match text), or a loud failure naming `what`. */
function grab(src, re, what) {
  const m = re.exec(src);
  if (!m) throw new Error("could not lift " + what + " -- rewrite this harness, don't stub it");
  return m[0];
}

/** Every position where `<keyword> name` starts a declaration line, as {at, indent}. */
function declarations(src, head, name, indent) {
  const lead = indent === undefined ? "[ \\t]*" : escapeRegExp(indent);
  const re = new RegExp("(^|\\n)(" + lead + ")(" + head + ")\\b", "g");
  const found = [];
  let m;
  while ((m = re.exec(src))) {
    const at = m.index + m[1].length;
    const after = src.slice(at + m[2].length + m[3].length);
    // the name must be the next token, so `function nameOther` and `function other(name)` miss
    const named = new RegExp("^\\s*\\*?\\s*" + escapeRegExp(name) + "\\b").exec(after);
    if (named) found.push({ at: at, indent: m[2] });
    if (m[0].length === 0) re.lastIndex++;
  }
  return found;
}

function where(opts) { return (opts && opts.where) || "the source"; }

/** The source text of `function name(...) { ... }` (async and generator forms included).
 *
 *  `opts.indent` pins the exact indent of the declaration line, which is how a page whose
 *  functions sit two spaces deep inside an IIFE is told apart from a helper of the same name
 *  nested further in. Without it the name must be unique in `src`; two candidates throw rather
 *  than lift the wrong one. `opts.where` is only the file name for the message. */
function liftSource(src, name, opts) {
  const o = opts || {};
  const hits = declarations(src, "(?:async[ \\t]+)?function", name, o.indent);
  if (!hits.length) {
    throw new Error(name + "() is gone from " + where(o) + " -- rewrite this harness, don't stub it");
  }
  if (hits.length > 1) {
    throw new Error(name + "() is declared " + hits.length + " times in " + where(o) +
      " -- pass { indent } to say which one");
  }
  const start = hits[0].at + hits[0].indent.length;
  const paren = src.indexOf("(", start);
  const afterParams = balanced(src, paren) + 1;
  const brace = src.indexOf("{", afterParams);
  if (brace < 0) throw new Error("no body found for " + name + "() in " + where(o));
  return src.slice(start, balanced(src, brace) + 1);
}

/** `function name` out of `src`, bound to `deps` BY NAME, and returned.
 *
 *  `deps` is an object of everything the function calls or reads; its keys become the lifted
 *  scope. A callee left out is an unbound identifier in the copy and fails when it runs. */
function lift(src, name, deps, opts) {
  const code = liftSource(src, name, opts);
  const names = Object.keys(deps || {});
  return new Function(...names, code + NL + "return " + name + ";")(...names.map((k) => deps[k]));
}

/** The text of `const|let|var name = ...;` through its terminating semicolon, so a role set, a
 *  lookup table or a list of cells is lifted from the page rather than typed a second time. */
function grabConst(src, name, opts) {
  const o = opts || {};
  const hits = declarations(src, "(?:const|let|var)", name, o.indent);
  if (!hits.length) {
    throw new Error(name + " is gone from " + where(o) + " -- rewrite this harness, don't stub it");
  }
  if (hits.length > 1) {
    throw new Error(name + " is declared " + hits.length + " times in " + where(o) +
      " -- pass { indent } to say which one");
  }
  const start = hits[0].at + hits[0].indent.length;
  const end = scan(src, start, ";");
  return src.slice(start, end + 1);
}

// ── the words a page can show ────────────────────────────────────────────────
/** Every string literal and every piece of template-literal text in `src`, in source order, as
 *  `{ text, line }` (line is 1-based, where the text starts).
 *
 *  WHY IT EXISTS. A test that wants to know whether a word can reach a person has to look at the
 *  strings, not the file. Grepping the file also finds the comments that explain a rename by
 *  quoting the old name, which is every comment worth reading, and a search that skips comment
 *  lines misses a `// note` at the end of a code line. So this walks the code the way `scan`
 *  does: a comment, a regular-expression literal and a division are told apart, and only the
 *  strings come out. Text inside a `${ ... }` substitution is code, so a string inside it is
 *  found too, in the order it appears. The text keeps its escapes as written (`\"` stays two
 *  characters): enough to look for words in, not a value to compute with.
 *
 *  Same limits as `scan`, on purpose (one scanner, one set of limits): a regular expression that
 *  follows `)` is read as a division. Throws on an unterminated string, template or comment, and
 *  names where. */
function stringLiterals(src) {
  const text = String(src);
  const out = [];
  const starts = [0];                           // where each line begins, for the line numbers
  for (let k = 0; k < text.length; k++) if (text[k] === NL) starts.push(k + 1);
  function lineOf(at) {
    let lo = 0;
    let hi = starts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= at) lo = mid; else hi = mid - 1;
    }
    return lo + 1;
  }
  /** The string that opens at `i`; returns the index just past its closing quote. */
  function quoted(i) {
    const q = text[i];
    let j = i + 1;
    let body = "";
    while (j < text.length) {
      const c = text[j];
      if (c === "\\") { body += text.slice(j, j + 2); j += 2; continue; }
      if (c === q) { out.push({ text: body, line: lineOf(i) }); return j + 1; }
      body += c;
      j++;
    }
    throw new Error("unterminated " + q + " string starting at " + i);
  }
  /** The template literal that opens at `i`; returns the index just past its closing backtick. */
  function template(i) {
    let j = i + 1;
    let body = "";
    let from = j;
    function flush() { if (body) out.push({ text: body, line: lineOf(from) }); body = ""; }
    while (j < text.length) {
      const c = text[j];
      if (c === "\\") { body += text.slice(j, j + 2); j += 2; continue; }
      if (c === "`") { flush(); return j + 1; }
      if (c === "$" && text[j + 1] === "{") {
        flush();
        j = walk(j + 2, "}") + 1;
        from = j;
        continue;
      }
      body += c;
      j++;
    }
    throw new Error("unterminated template literal starting at " + i);
  }
  /** Code from `i` to the unmatched `stop` character (its index), or to the end when `stop` is null. */
  function walk(i, stop) {
    let depth = 0;
    let prev = "";                              // the last significant character, regex or division
    let word = "";
    while (i < text.length) {
      const c = text[i];
      if (isSpace(c)) { i++; continue; }
      if (c === "'" || c === '"') { i = quoted(i); prev = "a"; word = ""; continue; }
      if (c === "`") { i = template(i); prev = "a"; word = ""; continue; }
      if (c === "/") {
        const n = text[i + 1];
        if (n === "/") { const e = text.indexOf(NL, i); i = e < 0 ? text.length : e; continue; }
        if (n === "*") {
          const e = text.indexOf("*/", i + 2);
          if (e < 0) throw new Error("unterminated comment starting at " + i);
          i = e + 2;
          continue;
        }
        if (prev === "" || REGEX_AFTER_CHAR.indexOf(prev) >= 0 || (prev === "a" && REGEX_AFTER_WORD.has(word))) {
          i = skipRegex(text, i);
          prev = "a"; word = "";
          continue;
        }
        prev = "/"; word = ""; i++;
        continue;
      }
      if (c === "{" || c === "(" || c === "[") { depth++; prev = c; word = ""; i++; continue; }
      if (c === "}" || c === ")" || c === "]") {
        if (depth === 0) {
          if (c === stop) return i;
          throw new Error("unbalanced " + c + " at " + i);
        }
        depth--;
        prev = c; word = ""; i++;
        continue;
      }
      if (isIdentStart(c) || (c >= "0" && c <= "9")) {
        let j = i + 1;
        while (j < text.length && isIdentPart(text[j])) j++;
        word = text.slice(i, j);
        prev = "a";
        i = j;
        continue;
      }
      prev = c; word = ""; i++;
    }
    if (stop !== null) throw new Error("ran off the end of the source looking for " + stop);
    // A whole file is balanced. Brackets still open here mean a quote, a regular expression or a
    // comment was misread somewhere above, and every string after that point is not to be trusted.
    if (depth !== 0) throw new Error("the source ends with " + depth + " bracket(s) still open");
    return i;
  }
  walk(0, null);
  return out;
}

// ── text out of markup ───────────────────────────────────────────────────────
/** One pass: drop every comment and every tag, quoted attribute values included. */
function stripOnce(html) {
  let out = "";
  let i = 0;
  const n = html.length;
  while (i < n) {
    const c = html[i];
    if (c !== "<") { out += c; i++; continue; }
    if (html.startsWith("<!--", i)) {
      const end = html.indexOf("-->", i + 4);
      if (end < 0) break;                       // an unterminated comment runs to the end
      i = end + 3;
      continue;
    }
    const next = html[i + 1];
    if (next !== undefined && (isIdentStart(next) || next === "/" || next === "!" || next === "?")) {
      let j = i + 1;
      let closed = false;
      while (j < n) {
        const d = html[j];
        if (d === '"' || d === "'") {
          const q = html.indexOf(d, j + 1);
          if (q < 0) { j = n; break; }
          j = q + 1;
          continue;
        }
        if (d === ">") { closed = true; break; }
        j++;
      }
      if (!closed) break;                       // an unterminated tag runs to the end
      i = j + 1;
      continue;
    }
    out += c;                                   // a lone "<" is text
    i++;
  }
  return out;
}

/** The text of some markup: comments and tags removed, repeated until nothing changes.
 *
 *  THE LOOP IS THE POINT. Removing tags once can MAKE a tag: `<<b>script>` loses its `<b>` and
 *  becomes `<script>`. A test that strips once and then asserts "no markup survived" passes on
 *  exactly the input that should fail it, which is also what CodeQL's incomplete-multi-character-
 *  sanitization query flags. Each pass either shortens the string or leaves it alone, so the loop
 *  ends; no regular expression is involved. */
function stripTags(html) {
  let s = String(html == null ? "" : html);
  for (;;) {
    const t = stripOnce(s);
    if (t === s) return t;
    s = t;
  }
}

// ── regular expressions built from text ──────────────────────────────────────
/** `text` with every regex metacharacter escaped, backslash included, so it matches itself. */
function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A RegExp that matches `text` literally. The one door for a variable into a pattern. */
function reOf(text, flags) {
  return new RegExp(escapeRegExp(text), flags);
}

module.exports = {
  NL, read, balanced, grab, liftSource, lift, grabConst, stripTags, stringLiterals, escapeRegExp, reOf,
};
