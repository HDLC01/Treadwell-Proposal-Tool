// Markup expression engine -- pure functions. No DOM, no fetch, no eval/new Function (prod CSP has
// no unsafe-eval). Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// Parses and evaluates the free-text `formula` column of backend/markup.py's markup_rules table --
// real Excel-style expressions, string literals and comparisons included, matching Gyp's own
// soft-costs cell verbatim: IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) - IF(E69>334900,.05,
// IF(E69>234450,.035,0)), "error"). A hand-rolled tokenizer + recursive-descent parser + tree
// evaluator, not eval -- see backend/markup.py's own docstring TODO for validate().
//
// SAFETY PROPERTY: a broken or unresolvable formula must render its line UNPRICEABLE, never
// silently price as $0. Arithmetic on a non-numeric value (a bare string, Kyle's own "error"
// sentinel, an IF with no matching branch) throws rather than coercing -- see requireNumber below.
// This is a deliberate divergence from Excel, which would sum a bare FALSE as 0.
(function (root, factory) {
  var api = factory();
  root.TWMarkup = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function ParseError(message) {
    this.name = "MarkupParseError";
    this.message = message;
    if (Error.captureStackTrace) Error.captureStackTrace(this, ParseError);
  }
  ParseError.prototype = Object.create(Error.prototype);
  ParseError.prototype.constructor = ParseError;

  function MarkupEvalError(message) {
    this.name = "MarkupEvalError";
    this.message = message;
    if (Error.captureStackTrace) Error.captureStackTrace(this, MarkupEvalError);
  }
  MarkupEvalError.prototype = Object.create(Error.prototype);
  MarkupEvalError.prototype.constructor = MarkupEvalError;

  // ---- tokenizer ----------------------------------------------------------

  function isDigit(c) { return c >= "0" && c <= "9"; }
  function isIdentStart(c) { return /[A-Za-z_]/.test(c); }
  function isIdentChar(c) { return /[A-Za-z0-9_.]/.test(c); }

  function tokenize(text) {
    var toks = [];
    var i = 0, n = text.length;
    function err(msg, pos) { throw new ParseError(msg + " at position " + pos); }
    while (i < n) {
      var c = text.charAt(i);
      if (c === " " || c === "\t" || c === "\n" || c === "\r") { i++; continue; }

      if (c === '"') {
        var start = i;
        i++;
        var buf = "";
        var closed = false;
        while (i < n) {
          if (text.charAt(i) === '"') {
            if (text.charAt(i + 1) === '"') { buf += '"'; i += 2; continue; }
            i++; closed = true; break;
          }
          buf += text.charAt(i); i++;
        }
        if (!closed) err("unterminated string literal (unpaired double-quote)", start);
        toks.push({ type: "STR", value: buf, pos: start });
        continue;
      }

      if (isDigit(c) || (c === "." && isDigit(text.charAt(i + 1)))) {
        var nstart = i;
        while (i < n && (isDigit(text.charAt(i)) || text.charAt(i) === ".")) i++;
        var raw = text.slice(nstart, i);
        if (!/^\d*\.?\d+$/.test(raw)) err("malformed number '" + raw + "'", nstart);
        toks.push({ type: "NUM", value: parseFloat(raw), pos: nstart });
        continue;
      }

      if (isIdentStart(c) || c === "$") {
        var istart = i;
        if (c === "$") i++;
        while (i < n && (isIdentChar(text.charAt(i)) || text.charAt(i) === "$")) i++;
        var name = text.slice(istart, i);
        if (name === "" || name === "$") err("stray reference marker", istart);
        toks.push({ type: "IDENT", value: name, pos: istart });
        continue;
      }

      if (c === "<") {
        if (text.charAt(i + 1) === "=") { toks.push({ type: "OP", value: "<=", pos: i }); i += 2; continue; }
        if (text.charAt(i + 1) === ">") { toks.push({ type: "OP", value: "<>", pos: i }); i += 2; continue; }
        toks.push({ type: "OP", value: "<", pos: i }); i++; continue;
      }
      if (c === ">") {
        if (text.charAt(i + 1) === "=") { toks.push({ type: "OP", value: ">=", pos: i }); i += 2; continue; }
        toks.push({ type: "OP", value: ">", pos: i }); i++; continue;
      }
      if ("=+-*/(),%".indexOf(c) !== -1) { toks.push({ type: "OP", value: c, pos: i }); i++; continue; }

      err("unexpected character '" + c + "'", i);
    }
    toks.push({ type: "EOF", value: null, pos: n });
    return toks;
  }

  function describeTok(t) {
    if (t.type === "EOF") return "end of formula";
    if (t.type === "STR") return "string " + JSON.stringify(t.value);
    return t.type + " '" + t.value + "'";
  }

  // ---- parser (recursive descent, fixed precedence) ------------------------
  //
  // comparison      := additive (( = | <> | < | <= | > | >= ) additive)*
  // additive        := multiplicative (( + | - ) multiplicative)*
  // multiplicative  := unary (( * | / ) unary)*
  // unary           := ( - | + ) unary | postfix
  // postfix         := primary ( '%' )*
  // primary         := NUMBER | STRING | IDENT | IDENT '(' args ')' | '(' comparison ')'

  var CMP_OPS = ["=", "<>", "<", "<=", ">", ">="];

  function Parser(tokens) {
    this.toks = tokens;
    this.i = 0;
  }
  Parser.prototype.peek = function () { return this.toks[this.i]; };
  Parser.prototype.next = function () { return this.toks[this.i++]; };
  Parser.prototype.expectOp = function (op) {
    var t = this.peek();
    if (!(t.type === "OP" && t.value === op)) {
      throw new ParseError("expected '" + op + "' but found " + describeTok(t) + " at position " + t.pos);
    }
    return this.next();
  };
  Parser.prototype.parseExpression = function () { return this.parseComparison(); };
  Parser.prototype.parseComparison = function () {
    var left = this.parseAdditive();
    while (this.peek().type === "OP" && CMP_OPS.indexOf(this.peek().value) !== -1) {
      var op = this.next().value;
      var right = this.parseAdditive();
      left = { type: "Compare", op: op, left: left, right: right };
    }
    return left;
  };
  Parser.prototype.parseAdditive = function () {
    var left = this.parseMultiplicative();
    while (this.peek().type === "OP" && (this.peek().value === "+" || this.peek().value === "-")) {
      var op = this.next().value;
      var right = this.parseMultiplicative();
      left = { type: "Binary", op: op, left: left, right: right };
    }
    return left;
  };
  Parser.prototype.parseMultiplicative = function () {
    var left = this.parseUnary();
    while (this.peek().type === "OP" && (this.peek().value === "*" || this.peek().value === "/")) {
      var op = this.next().value;
      var right = this.parseUnary();
      left = { type: "Binary", op: op, left: left, right: right };
    }
    return left;
  };
  Parser.prototype.parseUnary = function () {
    var t = this.peek();
    if (t.type === "OP" && (t.value === "-" || t.value === "+")) {
      this.next();
      return { type: "Unary", op: t.value, operand: this.parseUnary() };
    }
    return this.parsePostfix();
  };
  Parser.prototype.parsePostfix = function () {
    var node = this.parsePrimary();
    while (this.peek().type === "OP" && this.peek().value === "%") {
      this.next();
      node = { type: "Percent", operand: node };
    }
    return node;
  };
  Parser.prototype.parsePrimary = function () {
    var t = this.peek();
    if (t.type === "NUM") { this.next(); return { type: "Num", value: t.value }; }
    if (t.type === "STR") { this.next(); return { type: "Str", value: t.value }; }
    if (t.type === "OP" && t.value === "(") {
      this.next();
      var inner = this.parseExpression();
      this.expectOp(")");
      return inner;
    }
    if (t.type === "IDENT") {
      this.next();
      if (this.peek().type === "OP" && this.peek().value === "(") {
        this.next();
        var args = [];
        if (!(this.peek().type === "OP" && this.peek().value === ")")) {
          args.push(this.parseExpression());
          while (this.peek().type === "OP" && this.peek().value === ",") {
            this.next();
            args.push(this.parseExpression());
          }
        }
        this.expectOp(")");
        return { type: "Call", name: t.value, args: args };
      }
      return { type: "Ident", name: t.value };
    }
    throw new ParseError("unexpected " + describeTok(t) + " at position " + t.pos);
  };

  function parse(text) {
    if (typeof text !== "string" || text.trim() === "") {
      throw new ParseError("empty formula");
    }
    var tokens = tokenize(text);
    var p = new Parser(tokens);
    var ast = p.parseExpression();
    var t = p.peek();
    if (t.type !== "EOF") {
      throw new ParseError("unexpected trailing " + describeTok(t) + " at position " + t.pos);
    }
    return ast;
  }

  // ---- evaluator ------------------------------------------------------------

  function ctxGet(context, name) {
    context = context || {};
    var key = name.replace(/\$/g, "");
    if (Object.prototype.hasOwnProperty.call(context, key)) return context[key];
    var lower = key.toLowerCase();
    for (var k in context) {
      if (Object.prototype.hasOwnProperty.call(context, k) && k.toLowerCase() === lower) return context[k];
    }
    throw new MarkupEvalError("unresolved name '" + name + "'");
  }

  function requireNumber(v, label) {
    if (typeof v !== "number" || !isFinite(v)) {
      throw new MarkupEvalError((label ? label + ": " : "") + "expected a number, got " + JSON.stringify(v));
    }
    return v;
  }

  function truthy(v, label) {
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "string") {
      var s = v.trim().toLowerCase();
      if (s === "true" || s === "yes") return true;
      if (s === "false" || s === "no") return false;
    }
    throw new MarkupEvalError((label ? label + ": " : "") + "expected a condition (yes/no, true/false, or a number), got " + JSON.stringify(v));
  }

  function strEq(a, b) {
    if (typeof a === "string" && typeof b === "string") return a.toLowerCase() === b.toLowerCase();
    return a === b;
  }

  function compareValues(op, a, b) {
    if (op === "=") return strEq(a, b);
    if (op === "<>") return !strEq(a, b);
    if (typeof a === "number" && typeof b === "number") {
      switch (op) {
        case "<": return a < b;
        case "<=": return a <= b;
        case ">": return a > b;
        case ">=": return a >= b;
      }
    }
    if (typeof a === "string" && typeof b === "string") {
      var la = a.toLowerCase(), lb = b.toLowerCase();
      switch (op) {
        case "<": return la < lb;
        case "<=": return la <= lb;
        case ">": return la > lb;
        case ">=": return la >= lb;
      }
    }
    throw new MarkupEvalError("cannot compare " + JSON.stringify(a) + " " + op + " " + JSON.stringify(b) + " (mismatched types)");
  }

  // Excel ROUNDUP: away from zero, guarded to 12 significant figures against float noise.
  // Matches frontend/js/polish-bid-core.js's roundUp() exactly at digits=0.
  function excelRoundUp(n, digits) {
    digits = (digits === undefined || digits === null) ? 0 : digits;
    if (typeof digits !== "number" || !isFinite(digits)) {
      throw new MarkupEvalError("ROUNDUP: digits must be a number");
    }
    var factor = Math.pow(10, digits);
    var scaled = n * factor;
    var g = parseFloat(scaled.toPrecision(12));
    var r = g >= 0 ? Math.ceil(g) : -Math.ceil(-g);
    return r / factor;
  }

  function evalCall(name, argNodes, context) {
    var fname = String(name).toUpperCase();

    // IF is lazy -- only the taken branch is evaluated, so a formula like
    // IF(B5="yes", 1/D64, 0) does not throw on a job where D64 legitimately is not set yet.
    if (fname === "IF") {
      if (argNodes.length < 2 || argNodes.length > 3) {
        throw new MarkupEvalError("IF takes 2 or 3 arguments, got " + argNodes.length);
      }
      var cond = truthy(evaluate(argNodes[0], context), "IF condition");
      if (cond) return evaluate(argNodes[1], context);
      if (argNodes.length === 3) return evaluate(argNodes[2], context);
      // Excel's 2-arg IF returns boolean FALSE when the condition fails, and Excel sums a bare
      // FALSE as 0. This engine does NOT: arithmetic on this value throws in requireNumber with a
      // message telling the author to add an explicit third argument, rather than silently
      // producing a plausible-looking wrong number.
      return false;
    }

    var args = argNodes.map(function (n) { return evaluate(n, context); });

    switch (fname) {
      case "OR":
        if (!args.length) throw new MarkupEvalError("OR requires at least 1 argument");
        return args.some(function (a) { return truthy(a, "OR argument"); });
      case "AND":
        if (!args.length) throw new MarkupEvalError("AND requires at least 1 argument");
        return args.every(function (a) { return truthy(a, "AND argument"); });
      case "NOT":
        if (args.length !== 1) throw new MarkupEvalError("NOT takes exactly 1 argument");
        return !truthy(args[0], "NOT argument");
      case "MIN":
        if (!args.length) throw new MarkupEvalError("MIN requires at least 1 argument");
        return Math.min.apply(null, args.map(function (a) { return requireNumber(a, "MIN"); }));
      case "MAX":
        if (!args.length) throw new MarkupEvalError("MAX requires at least 1 argument");
        return Math.max.apply(null, args.map(function (a) { return requireNumber(a, "MAX"); }));
      case "ROUNDUP": {
        if (args.length < 1 || args.length > 2) throw new MarkupEvalError("ROUNDUP takes 1 or 2 arguments");
        var n = requireNumber(args[0], "ROUNDUP");
        var digits = args.length === 2 ? requireNumber(args[1], "ROUNDUP digits") : 0;
        return excelRoundUp(n, digits);
      }
      // BAND(value, ceiling1, rate1, ceiling2, rate2, ..., defaultRate) -- first pair whose ceiling
      // the value is STRICTLY BELOW wins, matching polish-bid-core.js's GP_BANDS lookup exactly
      // ([[6500,.52],[15000,.45],[22500,.35],[32500,.32],[null,.30]] becomes
      // BAND(sub_total, 6500,.52, 15000,.45, 22500,.35, 32500,.32, .30)).
      case "BAND": {
        if (args.length < 2 || (args.length % 2) !== 0) {
          throw new MarkupEvalError("BAND needs a value, zero or more ceiling/rate pairs, and a trailing default rate");
        }
        var value = requireNumber(args[0], "BAND value");
        var rest = args.slice(1);
        var def = requireNumber(rest[rest.length - 1], "BAND default rate");
        var pairs = rest.slice(0, rest.length - 1);
        for (var bi = 0; bi < pairs.length; bi += 2) {
          var ceiling = requireNumber(pairs[bi], "BAND ceiling");
          var rate = requireNumber(pairs[bi + 1], "BAND rate");
          if (value < ceiling) return rate;
        }
        return def;
      }
      // MARKUP(rate) -- the GP divide-up-then-subtract shape (D67 in polish-bid-core.js):
      // ROUNDUP(base/(1-rate),0) - ROUNDUP(base,0). `base` must be supplied in the context (the
      // running sum of every chain line above this one -- markup.py's own docstring calls this
      // "the running sum ABOVE it").
      case "MARKUP": {
        if (args.length !== 1) throw new MarkupEvalError("MARKUP takes exactly 1 argument (a rate)");
        var rate = requireNumber(args[0], "MARKUP rate");
        if (rate >= 1) throw new MarkupEvalError("MARKUP rate must be less than 100 percent, got " + (rate * 100));
        var base = requireNumber(ctxGet(context, "base"), "MARKUP base");
        return excelRoundUp(base / (1 - rate), 0) - excelRoundUp(base, 0);
      }
      default:
        throw new MarkupEvalError("unknown function '" + name + "'");
    }
  }

  function evaluate(node, context) {
    context = context || {};
    switch (node.type) {
      case "Num": return node.value;
      case "Str": return node.value;
      case "Ident": return ctxGet(context, node.name);
      case "Percent": return requireNumber(evaluate(node.operand, context), "percent") / 100;
      case "Unary": {
        var v = requireNumber(evaluate(node.operand, context), node.op);
        return node.op === "-" ? -v : v;
      }
      case "Binary": {
        var l = requireNumber(evaluate(node.left, context), node.op);
        var r = requireNumber(evaluate(node.right, context), node.op);
        switch (node.op) {
          case "+": return l + r;
          case "-": return l - r;
          case "*": return l * r;
          case "/":
            if (r === 0) throw new MarkupEvalError("division by zero");
            return l / r;
        }
        throw new MarkupEvalError("unknown operator '" + node.op + "'");
      }
      case "Compare":
        return compareValues(node.op, evaluate(node.left, context), evaluate(node.right, context));
      case "Call":
        return evalCall(node.name, node.args, context);
      default:
        throw new MarkupEvalError("unknown node type '" + node.type + "'");
    }
  }

  function run(text, context) {
    return evaluate(parse(text), context || {});
  }

  function validate(text) {
    try {
      parse(text);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: (e && e.message) ? e.message : String(e) };
    }
  }

  return {
    parse: parse,
    evaluate: evaluate,
    run: run,
    validate: validate,
    requireNumber: requireNumber,
    ParseError: ParseError,
    MarkupEvalError: MarkupEvalError,
  };
});
