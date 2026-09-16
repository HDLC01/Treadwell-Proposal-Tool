// Build-time comment stripper for the served frontend. Runs inside `docker build` ONLY
// (see the Dockerfile). The files in this repo are never touched by it -- the source stays
// readable, commented and diffable, because the comments here carry the reasoning that
// keeps this code correct.
//
// WHY. 44.7% of the raw bytes of frontend/**/*.js are comments, and 53.1% of styles.css.
// gzip does not make that free. Measured on the real files at the compression level the
// server actually uses (Starlette GZipMiddleware, level 9 -- the numbers below were checked
// against Content-Length on the wire, not just computed): the JS a browser downloads goes
// from 792,771 gzipped bytes to 348,127, and proposal-review.js alone from 136,365 to
// 46,193. The comments are worth every byte in the repo. They are worth nothing over HTTP.
//
// WHY ONLY COMMENTS, AND NOT terser. The harnesses in backend/tests/js/ lift functions out
// of the REAL frontend files with line-anchored regexes -- `^function foo\(...\) \{...\n\}`,
// `^const GYP_BASE = .*$`. Point the suite at a terser-minified tree and 1,797 of its 2,786
// assertions stop working (164 fail, 1,633 error): a mangled one-line file has nothing for
// those patterns to match. Minified bytes in the image and readable bytes in the tests is
// precisely the "every test green, production running something else" shape that has taken
// this app down before. terser's extra saving over this is 9 points of gzipped JS, and it
// is not worth buying with a test suite that can no longer see what ships.
//
// WHAT MAKES THIS ONE SAFE, rather than merely smaller:
//
//   1. A comment that spans newlines is replaced by exactly those newline bytes, CRLF
//      included. A block comment that spans none is replaced by a single space. A line
//      comment is replaced by nothing -- the newline that ended it was never part of it and
//      still follows. So the output has the same number of lines, the same line endings and
//      the same line NUMBERS as the source.
//
//   2. That makes two whole classes of breakage impossible rather than unlikely. Tokens
//      cannot be glued together (`a/*x*/b` becomes `a b`, never `ab`), and automatic
//      semicolon insertion cannot shift, because no newline is ever added or removed.
//
//   3. What is left is the removal of text the JS and CSS grammars both throw away. Nothing
//      in the frontend reads a function's own source (no Function.prototype.toString
//      anywhere), so no comment is load-bearing at runtime.
//
//   backend/tests/test_frontend_comment_strip.py re-derives all of this from the actual
//   output on every run: it walks source and stripped byte by byte and refuses any
//   difference that is not a comment span, and re-checks the result with `node --check`.
//
//   4. mtimes survive. Starlette's ETag is md5("<st_mtime>-<st_size>") and
//      NoCacheStaticFiles in backend/main.py leans on it: a deploy that does not change a
//      file must still answer 304. Writing a file gives it a fresh mtime, so each one is
//      restored to the source's. Without that, every deploy would re-send every asset to
//      every browser -- a bigger regression than this whole change is a win.
//
// A file that will not parse, or that comes out with a different number of lines, ABORTS
// the build. Shipping a half-transformed frontend is not a thing this is allowed to do.

"use strict";

const fs = require("fs");
const path = require("path");
const acorn = require("acorn");

const root = process.argv[2];
if (!root) {
  console.error("usage: node strip-comments.js <frontend-dir>");
  process.exit(2);
}

/** What a removed comment is replaced by. See note 1 above. */
function replacementFor(text, isLine) {
  if (isLine) return "";
  const newlines = text.replace(/[^\r\n]/g, "");
  return newlines.length ? newlines : " ";
}

function countLines(s) {
  return s.split("\n").length;
}

function countCrlf(s) {
  const m = s.match(/\r\n/g);
  return m ? m.length : 0;
}

/** JS: acorn tokenises, so "//" inside a string, a regex literal or a template is safe --
 *  and it does occur, in every https:// URL in the frontend. */
function stripJs(src) {
  const comments = [];
  const onComment = (block, text, start, end) => comments.push([start, end, !block]);
  acorn.parse(src, {
    ecmaVersion: "latest", allowReturnOutsideFunction: true, onComment,
  });                                            // throws -> the build aborts
  let out = "";
  let pos = 0;
  for (const [start, end, isLine] of comments) {
    out += src.slice(pos, start) + replacementFor(src.slice(start, end), isLine);
    pos = end;
  }
  out += src.slice(pos);
  acorn.parse(out, { ecmaVersion: "latest", allowReturnOutsideFunction: true });
  return out;
}

/** CSS: one comment form, no nesting. A string is the only place "/*" is not one. */
function stripCss(src) {
  let out = "";
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === '"' || c === "'") {
      const q = c;
      let j = i + 1;
      while (j < src.length && src[j] !== q) {
        if (src[j] === "\\") j++;
        j++;
      }
      out += src.slice(i, Math.min(j + 1, src.length));
      i = j + 1;
    } else if (c === "/" && src[i + 1] === "*") {
      const end = src.indexOf("*/", i + 2);
      const stop = end === -1 ? src.length : end + 2;
      out += replacementFor(src.slice(i, stop), false);
      i = stop;
    } else {
      out += c;
      i++;
    }
  }
  return out;
}

function walk(dir, acc) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, acc);
    else if (/\.(js|css)$/.test(entry.name)) acc.push(p);
  }
  return acc;
}

const files = walk(root, []).sort();
if (files.length === 0) {
  console.error("strip-comments: no .js or .css under " + root + " -- wrong path?");
  process.exit(2);
}

let before = 0;
let after = 0;
for (const file of files) {
  const src = fs.readFileSync(file, "utf8");
  let out;
  try {
    out = file.endsWith(".css") ? stripCss(src) : stripJs(src);
  } catch (e) {
    console.error("strip-comments: " + file + " could not be parsed: " + e.message);
    process.exit(1);
  }
  if (countLines(out) !== countLines(src) || countCrlf(out) !== countCrlf(src)) {
    console.error("strip-comments: " + file + " changed shape (in " + countLines(src) +
                  " lines / " + countCrlf(src) + " CRLF, out " + countLines(out) + " / " +
                  countCrlf(out) + ") -- refusing to ship it");
    process.exit(1);
  }
  const st = fs.statSync(file);
  before += Buffer.byteLength(src);
  after += Buffer.byteLength(out);
  fs.writeFileSync(file, out);
  fs.utimesSync(file, st.atime, st.mtime);       // keep the ETag stable across deploys
}

console.log("strip-comments: " + files.length + " files, " + before + " -> " + after +
            " raw bytes (" + (100 * (before - after) / before).toFixed(1) + "% was " +
            "comments); lines, line endings and mtimes unchanged");
