#include "select.hpp"

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <map>
#include <memory>

namespace gamut_core {
namespace internal {

namespace {

//   or     = and { "or" and }
//   and    = not { "and" not }
//   not    = [ "not" ] atom
//   atom   = name op value | "(" or ")"
//   op     = "==" | "!=" | "<" | "<=" | ">" | ">="
//   value  = number | string | word
//   string = '"' { any character but '"' } '"'

struct Token {
  enum Kind { Word, String, Open, Close, End } kind = End;
  std::string text;
  std::size_t at = 0;   // byte offset, for messages
};

bool is_op_char(char c) { return c == '=' || c == '!' || c == '<' || c == '>'; }

std::vector<Token> tokenize(const std::string& s) {
  std::vector<Token> out;
  std::size_t i = 0;
  while (i < s.size()) {
    const char c = s[i];
    if (std::isspace(static_cast<unsigned char>(c))) {
      ++i;
      continue;
    }
    Token t;
    t.at = i;
    if (c == '(' || c == ')') {
      t.kind = c == '(' ? Token::Open : Token::Close;
      t.text = std::string(1, c);
      ++i;
    } else if (c == '"') {
      const std::size_t end = s.find('"', i + 1);
      if (end == std::string::npos) {
        throw Error("", "where: the string starting at character " + std::to_string(i) +
                            " is not closed");
      }
      t.kind = Token::String;
      t.text = s.substr(i + 1, end - i - 1);
      i = end + 1;
    } else if (is_op_char(c)) {
      // An operator needs no spaces around it: "mach>0.7" is three tokens.
      // Names never hold these characters (SPEC.md section 9.3).
      const std::size_t n = i + 1 < s.size() && s[i + 1] == '=' ? 2 : 1;
      t.kind = Token::Word;
      t.text = s.substr(i, n);
      i += n;
    } else {
      std::size_t j = i;
      while (j < s.size() && !std::isspace(static_cast<unsigned char>(s[j])) && s[j] != '(' &&
             s[j] != ')' && s[j] != '"' && !is_op_char(s[j])) {
        ++j;
      }
      t.kind = Token::Word;
      t.text = s.substr(i, j - i);
      i = j;
    }
    out.push_back(t);
  }
  Token end;
  end.at = s.size();
  out.push_back(end);
  return out;
}

bool is_op(const std::string& w) {
  return w == "==" || w == "!=" || w == "<" || w == "<=" || w == ">" || w == ">=";
}

// An optional sign and decimal digits. *beyond is 1 above int64's range, -1
// below it, and 0 when *out holds the value.
bool integer(const std::string& w, std::int64_t* out, int* beyond) {
  const std::size_t start = !w.empty() && (w[0] == '-' || w[0] == '+') ? 1 : 0;
  if (start == w.size()) return false;
  for (std::size_t k = start; k < w.size(); ++k) {
    if (!std::isdigit(static_cast<unsigned char>(w[k]))) return false;
  }
  errno = 0;
  char* end = nullptr;
  const long long v = std::strtoll(w.c_str(), &end, 10);
  if (end == nullptr || *end != '\0') return false;
  *beyond = errno == ERANGE ? (w[0] == '-' ? -1 : 1) : 0;
  *out = static_cast<std::int64_t>(v);
  return true;
}

bool number(const std::string& w, double* out) {
  if (w.empty()) return false;
  char* end = nullptr;
  const double v = std::strtod(w.c_str(), &end);
  if (end == nullptr || *end != '\0') return false;
  // strtod accepts "nan" and "inf"; the grammar's numbers are decimal.
  for (const char c : w) {
    if (!(std::isdigit(static_cast<unsigned char>(c)) || c == '.' || c == 'e' || c == 'E' ||
          c == '+' || c == '-')) {
      return false;
    }
  }
  *out = v;
  return true;
}

// Parentheses nest at most this deep: the parser recurses once per level,
// and a where text may come from anyone.
const int kMaxNesting = 64;

class Parser {
 public:
  Parser(const Reader& r, const std::string& where) : r_(r), toks_(tokenize(where)) {
    rows_ = r.schema().rows;
    if (rows_ > kMaxRowsScanned) {
      throw Error("E23", "where: the file has " + std::to_string(rows_) + " rows, more than the " +
                             std::to_string(kMaxRowsScanned) + " a selection scans");
    }
  }

  std::vector<bool> parse() {
    std::vector<bool> v = parse_or();
    if (peek().kind != Token::End) fail("unexpected \"" + peek().text + "\"");
    return v;
  }

 private:
  const Token& peek() const { return toks_[pos_]; }
  Token next() { return toks_[pos_++]; }
  [[noreturn]] void fail(const std::string& why) const {
    throw Error("", "where: " + why + " at character " + std::to_string(peek().at));
  }

  std::vector<bool> parse_or() {
    std::vector<bool> v = parse_and();
    while (peek().kind == Token::Word && peek().text == "or") {
      next();
      const std::vector<bool> w = parse_and();
      for (std::size_t i = 0; i < v.size(); ++i) v[i] = v[i] || w[i];
    }
    return v;
  }

  std::vector<bool> parse_and() {
    std::vector<bool> v = parse_not();
    while (peek().kind == Token::Word && peek().text == "and") {
      next();
      const std::vector<bool> w = parse_not();
      for (std::size_t i = 0; i < v.size(); ++i) v[i] = v[i] && w[i];
    }
    return v;
  }

  std::vector<bool> parse_not() {
    if (peek().kind == Token::Word && peek().text == "not") {
      next();
      std::vector<bool> v = parse_atom();
      for (std::size_t i = 0; i < v.size(); ++i) v[i] = !v[i];
      return v;
    }
    return parse_atom();
  }

  std::vector<bool> parse_atom() {
    if (peek().kind == Token::Open) {
      if (++depth_ > kMaxNesting) {   // a cap (docs/security.md), so E23
        throw Error("E23", "where: parentheses are nested deeper than " +
                               std::to_string(kMaxNesting) + " levels at character " +
                               std::to_string(peek().at));
      }
      next();
      std::vector<bool> v = parse_or();
      if (peek().kind != Token::Close) fail("a \")\" is missing");
      next();
      --depth_;
      return v;
    }
    if (peek().kind != Token::Word) fail("a name is expected");
    const Token name = next();
    if (peek().kind != Token::Word || !is_op(peek().text)) {
      fail("an operator (==, !=, <, <=, >, >=) is expected after " + name.text);
    }
    const std::string op = next().text;
    if (peek().kind != Token::Word && peek().kind != Token::String) {
      fail("a value is expected after " + op);
    }
    const Token value = next();
    return compare(name, op, value);
  }

  std::vector<bool> compare(const Token& name, const std::string& op, const Token& value) {
    const Schema& s = r_.schema();
    std::vector<bool> out(static_cast<std::size_t>(rows_), false);
    // Columns are read a block of rows at a time, so memory stays bounded.
    const std::int64_t block = std::int64_t(1) << 20;
    const Selection all = Selection::all();
    if (const Label* l = s.label(name.text)) {
      if (op != "==" && op != "!=") {
        throw Error("", "where: the label " + name.text + " compares only by == or !=");
      }
      // Compared by code: the table names the entry once.
      const std::vector<std::string> table = r_.table(l->category);
      std::int64_t code = -1;
      for (std::size_t k = 0; k < table.size(); ++k) {
        if (table[k] == value.text) code = static_cast<std::int64_t>(k);
      }
      if (code < 0) {
        // The names it could be, up to a handful, as a choice to correct to.
        std::string names;
        for (std::size_t k = 0; k < table.size() && k < 8; ++k) {
          names += (k == 0 ? "" : ", ") + table[k];
        }
        if (table.size() > 8) names += ", ...";
        throw Error("E9", "where: \"" + value.text + "\" is not in the table of " + name.text +
                              (table.empty() ? std::string(", which is empty")
                                             : " (" + names + "); a name with spaces goes "
                                               "in double quotes"));
      }
      for (std::int64_t a = 0; a < rows_; a += block) {
        const std::int64_t b = std::min(rows_, a + block);
        std::vector<std::int64_t> codes(static_cast<std::size_t>(b - a));
        r_.read(name.text, Selection::range(a, b), all, DType::Int64, codes.data(),
                codes.size() * 8);
        for (std::int64_t i = a; i < b; ++i) {
          out[static_cast<std::size_t>(i)] =
              (codes[static_cast<std::size_t>(i - a)] == code) == (op == "==");
        }
      }
      return out;
    }
    const bool scalar = s.result(name.text) != nullptr && s.result(name.text)->where == "scalar";
    if (s.parameter(name.text) == nullptr && !scalar) {
      throw Error("", "where: \"" + name.text + "\" is not a parameter, scalar or label");
    }
    double v = 0.0;
    if (value.kind != Token::Word || !number(value.text, &v)) {
      throw Error("", "where: " + name.text + " compares with a number, and \"" + value.text +
                          "\" is not one");
    }
    // An int64 column against an integer literal compares exactly: as doubles,
    // values above 2^53 that differ would compare equal.
    const DType dtype = s.parameter(name.text) ? s.parameter(name.text)->dtype
                                               : s.result(name.text)->dtype;
    std::int64_t iv = 0;
    int beyond = 0;
    if (dtype == DType::Int64 && integer(value.text, &iv, &beyond)) {
      for (std::int64_t a = 0; a < rows_; a += block) {
        const std::int64_t b = std::min(rows_, a + block);
        std::vector<std::int64_t> col(static_cast<std::size_t>(b - a));
        r_.read(name.text, Selection::range(a, b), all, DType::Int64, col.data(),
                col.size() * 8);
        for (std::int64_t i = a; i < b; ++i) {
          const std::int64_t x = col[static_cast<std::size_t>(i - a)];
          // How x compares with the literal; one outside int64 is beyond every x.
          const int c = beyond != 0 ? -beyond : x < iv ? -1 : x > iv ? 1 : 0;
          out[static_cast<std::size_t>(i)] = op == "==" ? c == 0 : op == "!=" ? c != 0
                                             : op == "<"  ? c < 0  : op == "<=" ? c <= 0
                                             : op == ">"  ? c > 0  : c >= 0;
        }
      }
      return out;
    }
    for (std::int64_t a = 0; a < rows_; a += block) {
      const std::int64_t b = std::min(rows_, a + block);
      std::vector<double> col(static_cast<std::size_t>(b - a));
      r_.read(name.text, Selection::range(a, b), all, DType::Float64, col.data(),
              col.size() * 8);
      for (std::int64_t i = a; i < b; ++i) {
        const double x = col[static_cast<std::size_t>(i - a)];
        const std::size_t k = static_cast<std::size_t>(i);
        if (std::isnan(x)) continue;   // NaN compares false, every way
        if (op == "==") out[k] = x == v;
        else if (op == "!=") out[k] = x != v;
        else if (op == "<") out[k] = x < v;
        else if (op == "<=") out[k] = x <= v;
        else if (op == ">") out[k] = x > v;
        else out[k] = x >= v;
      }
    }
    return out;
  }

  const Reader& r_;
  std::vector<Token> toks_;
  std::size_t pos_ = 0;
  int depth_ = 0;
  std::int64_t rows_ = 0;
};

}  // namespace

std::vector<std::int64_t> select_rows(const Reader& reader, const std::string& where) {
  Parser p(reader, where);
  const std::vector<bool> keep = p.parse();
  std::vector<std::int64_t> out;
  for (std::size_t i = 0; i < keep.size(); ++i) {
    if (keep[i]) out.push_back(static_cast<std::int64_t>(i));
  }
  return out;
}

}  // namespace internal
}  // namespace gamut_core
